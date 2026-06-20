from fastapi import APIRouter, HTTPException, Request
from typing import List
from datetime import datetime
import json
import os

from ... import schemas
from ...config import settings
from ...database import get_db_context
from ...models import Character, Group, Image, PendingRequest, RequestStatus, User, UserRole
from ...security.permissions import require_admin_user_id, require_root_user_id
from ...services import CharacterService, GroupService, ImageService

router = APIRouter()


@router.get("/admins", response_model=List[schemas.AdminInfo])
async def get_admins(request: Request):
    """获取管理员列表（仅root）"""
    require_root_user_id(request)
    
    with get_db_context() as db:
        admins = db.query(User).filter(
            User.role.in_([UserRole.ROOT.value, UserRole.ADMIN.value])
        ).all()
        
        return [schemas.AdminInfo.model_validate(admin) for admin in admins]


@router.post("/admins")
async def add_admin(admin_data: schemas.AdminCreate, request: Request):
    """Add or promote an admin. Password login is disabled; access is via QQ ticket."""
    require_root_user_id(request)

    with get_db_context() as db:
        existing = db.query(User).filter(User.qq_number == admin_data.qq_number).first()

        if existing:
            if existing.role in [UserRole.ROOT.value, UserRole.ADMIN.value]:
                raise HTTPException(status_code=400, detail="?????????")
            existing.role = UserRole.ADMIN.value
            existing.password_hash = None
            db.commit()
            return {"message": f"?? {admin_data.qq_number} ???????"}

        new_admin = User(
            qq_number=admin_data.qq_number,
            role=UserRole.ADMIN.value,
            password_hash=None,
            nickname=f"???{admin_data.qq_number[-4:]}",
        )
        db.add(new_admin)
        db.commit()
        return {"message": f"??? {admin_data.qq_number} ????"}


@router.delete("/admins/{qq_number}")
async def remove_admin(qq_number: str, request: Request):
    """移除管理员（仅root）"""
    require_root_user_id(request)
    
    with get_db_context() as db:
        user = db.query(User).filter(User.qq_number == qq_number).first()
        if not user:
            raise HTTPException(status_code=404, detail="用户不存在")
        
        if user.role == UserRole.ROOT.value:
            raise HTTPException(status_code=400, detail="不能移除root用户")
        
        if user.role != UserRole.ADMIN.value:
            raise HTTPException(status_code=400, detail="该用户不是管理员")
        
        # 降级为普通用户
        user.role = UserRole.USER.value
        user.password_hash = None
        db.commit()
        
        return {"message": f"用户 {qq_number} 已被移除管理员权限"}
