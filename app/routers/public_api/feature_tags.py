from fastapi import APIRouter, HTTPException, Query, Request
from typing import List, Union

from ... import models, schemas
from ...config import settings
from ...database import get_db_context
from ...models import User, UserRole
from ...services import FeatureTagService
from ..auth import get_current_session

router = APIRouter()


def _require_logged_in_user(request: Request, db) -> None:
    session = get_current_session(request, db)
    if not session:
        raise HTTPException(status_code=401, detail="Login required")
    if session.get("is_guest"):
        raise HTTPException(status_code=403, detail="User login required")
    user = db.query(User).filter(User.id == session["user_id"]).first()
    if not user:
        raise HTTPException(status_code=401, detail="Invalid session")
    if user.role not in [UserRole.ROOT.value, UserRole.ADMIN.value, UserRole.USER.value]:
        raise HTTPException(status_code=403, detail="User login required")


@router.get("/feature-tags/", response_model=List[schemas.FeatureTag])
def get_feature_tags(
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=settings.MAX_PAGE_SIZE),
):
    with get_db_context() as db:
        return FeatureTagService.get_feature_tags(db, skip, limit)


@router.post("/feature-tags/", response_model=Union[schemas.FeatureTag, dict])
def create_feature_tag(tag: schemas.FeatureTagCreate, request: Request):
    with get_db_context() as db:
        _require_logged_in_user(request, db)
        existing = db.query(models.FeatureTag).filter(models.FeatureTag.name == tag.name).first()
        if existing:
            raise HTTPException(status_code=400, detail="Feature tag already exists")
        return FeatureTagService.create_feature_tag(db, tag)


@router.put("/feature-tags/{tag_id}", response_model=schemas.FeatureTag)
def update_feature_tag(tag_id: int, tag_update: schemas.FeatureTagUpdate, request: Request):
    with get_db_context() as db:
        _require_logged_in_user(request, db)
        if tag_update.name:
            existing = db.query(models.FeatureTag).filter(
                models.FeatureTag.name == tag_update.name,
                models.FeatureTag.id != tag_id
            ).first()
            if existing:
                raise HTTPException(status_code=400, detail="Feature tag already exists")
        updated = FeatureTagService.update_feature_tag(db, tag_id, tag_update)
        if not updated:
            raise HTTPException(status_code=404, detail="Feature tag not found")
        return updated


@router.delete("/feature-tags/{tag_id}")
def delete_feature_tag(tag_id: int, request: Request):
    with get_db_context() as db:
        _require_logged_in_user(request, db)
        success = FeatureTagService.delete_feature_tag(db, tag_id)
        if not success:
            raise HTTPException(status_code=404, detail="Feature tag not found")
        return {"message": "Feature tag deleted"}
