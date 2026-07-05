from fastapi import APIRouter, HTTPException, UploadFile, File, Form, Request
from typing import List, Optional, Union

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


# 角色相关路由
@router.post("/characters/", response_model=Union[schemas.CharacterWithGroupName, dict])
def create_character(character: schemas.CharacterCreate, request: Request):
    """创建角色"""
    with get_db_context() as db:
        existing = db.query(models.Character).filter(
            models.Character.group_id == character.group_id,
            models.Character.name == character.name
        ).first()
        if existing:
            raise HTTPException(status_code=400, detail="该分组下已存在同名角色")

        session = get_current_session(request, db)
        is_admin = False
        is_logged_in_user = False
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
                    is_logged_in_user = True

        # 校验分组是否存在
        group_exists = db.query(models.Group).filter(models.Group.id == character.group_id).first()
        if not group_exists:
            raise HTTPException(status_code=400, detail="选中的分组不存在")

        if character.feature_tag_ids:
            existing_tags = db.query(models.FeatureTag).filter(
                models.FeatureTag.id.in_(character.feature_tag_ids)
            ).all()
            if len(existing_tags) != len(character.feature_tag_ids):
                missing_ids = set(character.feature_tag_ids) - set(t.id for t in existing_tags)
                raise HTTPException(status_code=400, detail=f"Selected feature tags do not exist: {missing_ids}")

        if is_admin or is_logged_in_user:
            return CharacterService.create_character(db, character)

        pending_request = PendingRequest(
            request_type="character_add",
            user_id=user_id,
            guest_ip=guest_ip,
            image_data=json.dumps({
                "name": character.name,
                "group_id": character.group_id,
                "description": character.description,
                "nicknames": character.nicknames,
                "feature_tag_ids": character.feature_tag_ids or []
            })
        )
        db.add(pending_request)
        db.commit()
        return {"message": "提交成功，等待管理员审核"}

@router.get("/characters/", response_model=List[schemas.CharacterWithGroupName])
def get_characters(group_id: Optional[int] = None, skip: int = 0, limit: int = 1000):
    """获取角色列表"""
    with get_db_context() as db:
        return CharacterService.get_characters(db, group_id, skip, limit)

@router.get("/characters/{character_id}", response_model=schemas.CharacterWithGroupName)
def get_character(character_id: int):
    """获取单个角色"""
    with get_db_context() as db:
        character = CharacterService.get_character(db, character_id)
        if not character:
            raise HTTPException(status_code=404, detail="Character not found")
        return character

@router.put("/characters/{character_id}", response_model=Union[schemas.CharacterWithGroupName, dict])
def update_character(character_id: int, character_update: schemas.CharacterUpdate, request: Request):
    """更新角色"""
    with get_db_context() as db:
        session = get_current_session(request, db)
        is_admin = False
        is_logged_in_user = False
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
                    is_logged_in_user = True

        # 校验角色是否存在
        existing = db.query(models.Character).filter(models.Character.id == character_id).first()
        if not existing:
            raise HTTPException(status_code=404, detail="Character not found")

        if character_update.group_id:
            group_exists = db.query(models.Group).filter(models.Group.id == character_update.group_id).first()
            if not group_exists:
                raise HTTPException(status_code=400, detail="选中的分组不存在")

        if character_update.feature_tag_ids is not None:
            existing_tags = db.query(models.FeatureTag).filter(
                models.FeatureTag.id.in_(character_update.feature_tag_ids)
            ).all() if character_update.feature_tag_ids else []
            if len(existing_tags) != len(character_update.feature_tag_ids or []):
                missing_ids = set(character_update.feature_tag_ids or []) - set(t.id for t in existing_tags)
                raise HTTPException(status_code=400, detail=f"Selected feature tags do not exist: {missing_ids}")

        if is_admin:
            character = CharacterService.update_character(db, character_id, character_update)
            return character

        update_data = character_update.dict(exclude_unset=True)
        update_data["character_id"] = character_id
        pending_request = PendingRequest(
            request_type="character_edit",
            user_id=user_id,
            guest_ip=guest_ip,
            image_data=json.dumps(update_data)
        )
        db.add(pending_request)
        db.commit()
        return {"message": "提交成功，等待管理员审核"}

@router.delete("/characters/{character_id}")
def delete_character(character_id: int, request: Request):
    """删除角色"""
    with get_db_context() as db:
        session = get_current_session(request, db)
        is_admin = False
        is_logged_in_user = False
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
                    is_logged_in_user = True

        # 校验角色是否存在
        existing = db.query(models.Character).filter(models.Character.id == character_id).first()
        if not existing:
            raise HTTPException(status_code=404, detail="Character not found")

        if is_admin:
            success = CharacterService.delete_character(db, character_id)
            if not success:
                raise HTTPException(status_code=404, detail="Character not found")
            return {"message": "角色删除成功"}

        pending_request = PendingRequest(
            request_type="character_delete",
            user_id=user_id,
            guest_ip=guest_ip,
            image_data=json.dumps({
                "character_id": character_id
            })
        )
        db.add(pending_request)
        db.commit()
        return {"message": "提交成功，等待管理员审核"}
