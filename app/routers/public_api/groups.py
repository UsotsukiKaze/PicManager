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


# 分组相关路由
@router.post("/groups/", response_model=Union[schemas.Group, dict])
def create_group(group: schemas.GroupCreate, request: Request):
    """创建分组"""
    with get_db_context() as db:
        existing = db.query(models.Group).filter(models.Group.name == group.name).first()
        if existing:
            raise HTTPException(status_code=400, detail="分组名称已存在")

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

        if is_admin or is_logged_in_user:
            return GroupService.create_group(db, group)

        pending_request = PendingRequest(
            request_type="group_add",
            user_id=user_id,
            guest_ip=guest_ip,
            image_data=json.dumps({
                "name": group.name,
                "description": group.description
            })
        )
        db.add(pending_request)
        db.commit()
        return {"message": "提交成功，等待管理员审核"}

@router.get("/groups/", response_model=List[schemas.Group])
def get_groups(skip: int = 0, limit: int = 100):
    """获取分组列表"""
    with get_db_context() as db:
        return GroupService.get_groups(db, skip, limit)

@router.get("/groups/{group_id}", response_model=schemas.Group)
def get_group(group_id: int):
    """获取单个分组"""
    with get_db_context() as db:
        group = GroupService.get_group(db, group_id)
        if not group:
            raise HTTPException(status_code=404, detail="Group not found")
        return group

@router.put("/groups/{group_id}", response_model=Union[schemas.Group, dict])
def update_group(group_id: int, group_update: schemas.GroupUpdate, request: Request):
    """更新分组"""
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

        # 校验分组是否存在
        existing = db.query(models.Group).filter(models.Group.id == group_id).first()
        if not existing:
            raise HTTPException(status_code=404, detail="Group not found")

        if is_admin:
            group = GroupService.update_group(db, group_id, group_update)
            return group

        update_data = group_update.dict(exclude_unset=True)
        update_data["group_id"] = group_id
        pending_request = PendingRequest(
            request_type="group_edit",
            user_id=user_id,
            guest_ip=guest_ip,
            image_data=json.dumps(update_data)
        )
        db.add(pending_request)
        db.commit()
        return {"message": "提交成功，等待管理员审核"}

@router.delete("/groups/{group_id}")
def delete_group(group_id: int, request: Request):
    """删除分组"""
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

        # 校验分组是否存在
        existing = db.query(models.Group).filter(models.Group.id == group_id).first()
        if not existing:
            raise HTTPException(status_code=404, detail="Group not found")

        if is_admin:
            success = GroupService.delete_group(db, group_id)
            if not success:
                raise HTTPException(status_code=404, detail="Group not found")
            return {"message": "分组删除成功"}

        pending_request = PendingRequest(
            request_type="group_delete",
            user_id=user_id,
            guest_ip=guest_ip,
            image_data=json.dumps({
                "group_id": group_id
            })
        )
        db.add(pending_request)
        db.commit()
        return {"message": "提交成功，等待管理员审核"}
