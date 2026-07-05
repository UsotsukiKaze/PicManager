from fastapi import APIRouter, HTTPException, Request
from typing import List, Union

from ... import models, schemas
from ...database import get_db_context
from ...models import User, UserRole
from ...services import FeatureTagService
from ..auth import get_current_session

router = APIRouter()


def _is_logged_in_or_admin(request: Request, db) -> bool:
    session = get_current_session(request, db)
    if not session or session.get("is_guest"):
        return False
    user = db.query(User).filter(User.id == session["user_id"]).first()
    return bool(user and user.role in [UserRole.ROOT.value, UserRole.ADMIN.value, UserRole.USER.value])


@router.get("/feature-tags/", response_model=List[schemas.FeatureTag])
def get_feature_tags(skip: int = 0, limit: int = 1000):
    with get_db_context() as db:
        return FeatureTagService.get_feature_tags(db, skip, limit)


@router.post("/feature-tags/", response_model=Union[schemas.FeatureTag, dict])
def create_feature_tag(tag: schemas.FeatureTagCreate, request: Request):
    with get_db_context() as db:
        if not _is_logged_in_or_admin(request, db):
            raise HTTPException(status_code=403, detail="Login required")
        existing = db.query(models.FeatureTag).filter(models.FeatureTag.name == tag.name).first()
        if existing:
            raise HTTPException(status_code=400, detail="Feature tag already exists")
        return FeatureTagService.create_feature_tag(db, tag)


@router.put("/feature-tags/{tag_id}", response_model=schemas.FeatureTag)
def update_feature_tag(tag_id: int, tag_update: schemas.FeatureTagUpdate, request: Request):
    with get_db_context() as db:
        if not _is_logged_in_or_admin(request, db):
            raise HTTPException(status_code=403, detail="Login required")
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
        if not _is_logged_in_or_admin(request, db):
            raise HTTPException(status_code=403, detail="Login required")
        success = FeatureTagService.delete_feature_tag(db, tag_id)
        if not success:
            raise HTTPException(status_code=404, detail="Feature tag not found")
        return {"message": "Feature tag deleted"}
