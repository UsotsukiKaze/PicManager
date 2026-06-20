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


@router.get("/stats")
async def get_admin_stats(request: Request):
    """获取管理统计信息"""
    require_admin_user_id(request)
    
    with get_db_context() as db:
        pending_count = db.query(PendingRequest).filter(
            PendingRequest.status == RequestStatus.PENDING.value
        ).count()
        
        total_users = db.query(User).count()
        admin_count = db.query(User).filter(
            User.role.in_([UserRole.ROOT.value, UserRole.ADMIN.value])
        ).count()
        
        return {
            "pending_requests": pending_count,
            "total_users": total_users,
            "admin_count": admin_count
        }
