from fastapi import APIRouter, HTTPException, UploadFile, File, Form, Request
from fastapi.responses import FileResponse
from typing import List, Optional, Union
from pathlib import Path
from urllib.parse import quote

from ...database import get_db_context
from ...services import GroupService, CharacterService, ImageService
from ...models import User, UserRole, PendingRequest, ImageViewCount, CharacterQueryCount, RequestStatus, Group, Character
from ... import models, schemas
from ...config import settings
from ...logger import log_error
from ..auth import get_current_session, check_guest_limit
import tempfile
import os
import json
from datetime import datetime

router = APIRouter()


# 图片相关路由
@router.get("/images/search", response_model=schemas.ImageSearchResult)
def search_images(
    group_id: Optional[int] = None,
    character_id: Optional[int] = None,
    feature_tag_id: Optional[int] = None,
    pid: Optional[str] = None,
    description: Optional[str] = None,
    limit: int = 50,
    offset: int = 0
):
    """搜索图片"""
    with get_db_context() as db:
        # 仅在明确按角色查询时统计角色查询次数（排除随机抽取）
        if character_id:
            character = db.query(models.Character).filter(models.Character.id == character_id).first()
            if character:
                record = db.query(CharacterQueryCount).filter(
                    CharacterQueryCount.character_id == character_id
                ).first()
                if not record:
                    record = CharacterQueryCount(character_id=character_id, query_count=0)
                    db.add(record)
                record.query_count += 1

        params = schemas.ImageSearchParams(
            group_id=group_id,
            character_id=character_id,
            feature_tag_id=feature_tag_id,
            pid=pid,
            description=description,
            limit=limit,
            offset=offset
        )
        images, total = ImageService.search_images(db, params)
        return schemas.ImageSearchResult(
            images=images,
            total=total,
            offset=offset,
            limit=limit
        )

@router.get("/images/random", response_model=schemas.RandomImageResponse)
def get_random_image(
    group_id: Optional[int] = None,
    character_id: Optional[int] = None,
    exclude_group_id: Optional[int] = None,
    feature_tag_id: Optional[int] = None
):
    """随机获取图片"""
    with get_db_context() as db:
        image = ImageService.get_random_image(db, group_id, character_id, exclude_group_id, feature_tag_id)
        if not image:
            raise HTTPException(status_code=404, detail="Image not found")
        return image

@router.get("/images/{image_id}", response_model=schemas.ImageWithCharacters)
def get_image(image_id: str):
    """获取单个图片信息"""
    with get_db_context() as db:
        image = ImageService.get_image(db, image_id)
        if not image:
            raise HTTPException(status_code=404, detail="Image not found")

        record = db.query(ImageViewCount).filter(ImageViewCount.image_id == image_id).first()
        if not record:
            record = ImageViewCount(image_id=image_id, view_count=0)
            db.add(record)
        record.view_count += 1
        return image


@router.get("/images/{image_id}/download")
def download_image(image_id: str):
    """Download a managed original image through an id-based safe endpoint."""
    with get_db_context() as db:
        db_image = db.query(models.Image).filter(
            models.Image.image_id == image_id,
            models.Image.file_status == ImageService.AVAILABLE
        ).first()
        if not db_image:
            raise HTTPException(status_code=404, detail="Image not found")
        if not ImageService.image_file_exists(db_image):
            ImageService.mark_file_status(db, db_image, exists=False)
            db.commit()
            raise HTTPException(status_code=404, detail="Image not found")

        full_path = Path(ImageService.image_full_path(db_image)).resolve()
        store_root = Path(settings.STORE_PATH).resolve()
        try:
            full_path.relative_to(store_root)
        except ValueError as exc:
            raise HTTPException(status_code=404, detail="Image not found") from exc

        original_name = db_image.original_filename or f"{db_image.image_id}.{db_image.file_extension}"
        safe_name = Path(original_name).name or f"{db_image.image_id}.{db_image.file_extension}"
        encoded_name = quote(safe_name)
        response = FileResponse(
            full_path,
            media_type="application/octet-stream",
            filename=safe_name,
        )
        response.headers["Content-Disposition"] = f"attachment; filename*=UTF-8''{encoded_name}"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Cache-Control"] = "private, max-age=3600"
        return response



@router.put("/images/{image_id}")
def update_image(image_id: str, image_update: schemas.ImageUpdate, request: Request):
    """更新图片信息"""
    # 检查用户权限
    with get_db_context() as db:
        session = get_current_session(request, db)
        is_admin = False
        user_id = None
        guest_ip = None
        
        if session:
            if session.get("is_guest"):
                guest_ip = session.get("guest_ip")
                if not check_guest_limit(db, guest_ip):
                    raise HTTPException(status_code=429, detail="今日操作次数已用完")
            else:
                user = db.query(User).filter(User.id == session["user_id"]).first()
                if user:
                    user_id = user.id
                    is_admin = user.role in [UserRole.ROOT.value, UserRole.ADMIN.value]

        # 校验图片是否存在
        db_image = db.query(models.Image).filter(models.Image.image_id == image_id).first()
        if not db_image:
            raise HTTPException(status_code=404, detail="Image not found")

        # 校验角色ID（如有）
        if image_update.character_ids is not None:
            try:
                character_ids = [int(cid) for cid in image_update.character_ids]
            except (TypeError, ValueError):
                raise HTTPException(status_code=400, detail="Invalid character_ids format")

            if character_ids:
                existing_characters = db.query(models.Character).filter(
                    models.Character.id.in_(character_ids)
                ).all()
                if len(existing_characters) != len(character_ids):
                    missing_ids = set(character_ids) - set(c.id for c in existing_characters)
                    raise HTTPException(status_code=400, detail=f"选中的某些角色不存在: {missing_ids}")
            image_update.character_ids = character_ids

        if image_update.group_ids is not None:
            try:
                group_ids = list(dict.fromkeys([int(gid) for gid in image_update.group_ids]))
            except (TypeError, ValueError):
                raise HTTPException(status_code=400, detail="Invalid group_ids format")
            if group_ids:
                existing_groups = db.query(models.Group).filter(
                    models.Group.id.in_(group_ids)
                ).all()
                if len(existing_groups) != len(group_ids):
                    missing_ids = set(group_ids) - set(g.id for g in existing_groups)
                    raise HTTPException(status_code=400, detail=f"Selected groups do not exist: {missing_ids}")
            image_update.group_ids = group_ids

        if image_update.feature_tag_ids is not None:
            try:
                feature_tag_ids = list(dict.fromkeys([int(tid) for tid in image_update.feature_tag_ids]))
            except (TypeError, ValueError):
                raise HTTPException(status_code=400, detail="Invalid feature_tag_ids format")
            if feature_tag_ids:
                existing_tags = db.query(models.FeatureTag).filter(
                    models.FeatureTag.id.in_(feature_tag_ids)
                ).all()
                if len(existing_tags) != len(feature_tag_ids):
                    missing_ids = set(feature_tag_ids) - set(t.id for t in existing_tags)
                    raise HTTPException(status_code=400, detail=f"Selected feature tags do not exist: {missing_ids}")
            image_update.feature_tag_ids = feature_tag_ids
        
        if is_admin:
            # 管理员直接更新
            image = ImageService.update_image(db, image_id, image_update)
            if not image:
                raise HTTPException(status_code=404, detail="Image not found")
            return {"message": "图片信息更新成功", "status": "success"}

        # 非管理员，创建待审核请求
        pending_request = PendingRequest(
            request_type="edit",
            user_id=user_id,
            guest_ip=guest_ip,
            image_id=image_id,
            image_data=json.dumps({
                "pid": image_update.pid,
                "description": image_update.description,
                "character_ids": image_update.character_ids,
                "group_ids": image_update.group_ids,
                "feature_tag_ids": image_update.feature_tag_ids
            })
        )
        db.add(pending_request)
        db.commit()

        return {"message": "已提交，等待管理员审核", "status": "pending"}

@router.delete("/images/{image_id}")
def delete_image(image_id: str, request: Request):
    """删除图片"""
    # 检查用户权限
    with get_db_context() as db:
        session = get_current_session(request, db)
        is_admin = False
        user_id = None
        guest_ip = None
        
        if session:
            if session.get("is_guest"):
                guest_ip = session.get("guest_ip")
                if not check_guest_limit(db, guest_ip):
                    raise HTTPException(status_code=429, detail="今日操作次数已用完")
            else:
                user = db.query(User).filter(User.id == session["user_id"]).first()
                if user:
                    user_id = user.id
                    is_admin = user.role in [UserRole.ROOT.value, UserRole.ADMIN.value]

        # 校验图片是否存在
        db_image = db.query(models.Image).filter(models.Image.image_id == image_id).first()
        if not db_image:
            raise HTTPException(status_code=404, detail="Image not found")
        
        if is_admin:
            # 管理员直接删除
            store_path = settings.STORE_PATH
            success = ImageService.delete_image(db, image_id, store_path)
            if not success:
                raise HTTPException(status_code=404, detail="Image not found")
            return {"message": "图片删除成功", "status": "success"}

        # 非管理员，创建待审核请求
        pending_request = PendingRequest(
            request_type="delete",
            user_id=user_id,
            guest_ip=guest_ip,
            image_id=image_id
        )
        db.add(pending_request)
        db.commit()

        return {"message": "已提交，等待管理员审核", "status": "pending"}
