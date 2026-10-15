from datetime import datetime, timedelta
import time

from fastapi import APIRouter
from sqlalchemy import func

from ... import models
from ...contributions import calculate_contribution_score
from ...database import get_db_context
from ...models import Character, Group, PendingRequest, RequestStatus, User
from ...services import ImageService

router = APIRouter()

_RANKINGS_CACHE = {"key": None, "expires_at": 0.0, "data": None}


@router.get("/rankings")
def get_rankings(limit: int = 10, group_id: int | None = None):
    limit = max(1, min(limit, 50))
    now = time.time()
    if (
        _RANKINGS_CACHE["key"] == (limit, group_id)
        and _RANKINGS_CACHE["data"] is not None
        and _RANKINGS_CACHE["expires_at"] > now
    ):
        return _RANKINGS_CACHE["data"]
    """获取贡献榜、角色图片数榜和分组收藏榜"""
    with get_db_context() as db:
        # 贡献榜（仅登录用户）
        approved_requests = db.query(PendingRequest).filter(
            PendingRequest.user_id.isnot(None),
            PendingRequest.status == RequestStatus.APPROVED.value
        ).all()

        contribution_map = {}
        for req in approved_requests:
            if not req.user_id:
                continue
            user_score = contribution_map.setdefault(req.user_id, {
                "score": 0,
                "counts": {}
            })
            user_score["score"] += calculate_contribution_score((req.request_type,))

        user_ids = list(contribution_map.keys())
        users = db.query(User).filter(User.id.in_(user_ids)).all() if user_ids else []
        user_map = {user.id: user for user in users}

        contribution_list = []
        for user_id, info in contribution_map.items():
            user = user_map.get(user_id)
            if not user:
                continue
            contribution_list.append({
                "user_id": user_id,
                "nickname": user.nickname or user.qq_number,
                "qq_number": user.qq_number,
                "avatar_url": user.avatar_url,
                "role": user.role,
                "score": info["score"]
            })

        contribution_list.sort(key=lambda item: item["score"], reverse=True)
        contribution_list = contribution_list[:limit]

        # Count library images, not query/view events. Aggregate independently
        # so joining group roles cannot multiply image totals.
        character_images = db.query(
            models.image_character_association.c.character_id.label('character_id'),
            func.count(func.distinct(models.Image.image_id)).label('image_count'),
        ).join(models.Image, models.Image.image_id == models.image_character_association.c.image_id).filter(
            models.Image.file_status == ImageService.AVAILABLE,
        ).group_by(models.image_character_association.c.character_id).subquery()
        count = func.coalesce(character_images.c.image_count, 0)
        character_query = db.query(Character.id, Character.name, Character.avatar_url,
            Group.name.label('group_name'), count.label('image_count')).outerjoin(
                Group, Group.id == Character.group_id).outerjoin(
                character_images, character_images.c.character_id == Character.id)
        if group_id is not None:
            character_query = character_query.filter(Character.group_id == group_id)
        characters = character_query.order_by(
                count.desc(), Character.name.asc(), Character.id.asc()).limit(limit).all()
        character_rank = [{
            'character_id': row.id, 'name': row.name, 'group_name': row.group_name,
            'avatar_url': row.avatar_url or '/favicon.ico',
            'image_count': row.image_count, 'count': row.image_count,
        } for row in characters]

        group_images = db.query(
            models.image_group_association.c.group_id.label('group_id'),
            func.count(func.distinct(models.Image.image_id)).label('image_count'),
        ).join(models.Image, models.Image.image_id == models.image_group_association.c.image_id).filter(
            models.Image.file_status == ImageService.AVAILABLE,
        ).group_by(models.image_group_association.c.group_id).subquery()
        group_roles = db.query(Character.group_id.label('group_id'),
            func.count(Character.id).label('character_count')).group_by(Character.group_id).subquery()
        image_count = func.coalesce(group_images.c.image_count, 0)
        character_count = func.coalesce(group_roles.c.character_count, 0)
        groups = db.query(Group.id, Group.name, Group.avatar_url,
            image_count.label('image_count'), character_count.label('character_count')).outerjoin(
                group_images, group_images.c.group_id == Group.id).outerjoin(
                group_roles, group_roles.c.group_id == Group.id).order_by(
                image_count.desc(), character_count.desc(), Group.name.asc(), Group.id.asc()).limit(limit).all()
        group_rank = [{
            'group_id': row.id, 'name': row.name, 'avatar_url': row.avatar_url or '/favicon.ico',
            'image_count': row.image_count, 'character_count': row.character_count, 'count': row.image_count,
        } for row in groups]

        recent_since = datetime.utcnow() - timedelta(days=30)
        recent_group_rows = db.query(
            Group.id,
            Group.name,
            Group.avatar_url,
            func.count(func.distinct(models.Image.image_id)).label("image_count"),
        ).join(
            models.image_group_association,
            models.image_group_association.c.group_id == Group.id,
        ).join(
            models.Image,
            models.Image.image_id == models.image_group_association.c.image_id,
        ).filter(
            models.Image.file_status == ImageService.AVAILABLE,
            models.Image.created_at >= recent_since,
        ).group_by(
            Group.id,
            Group.name,
            Group.avatar_url,
        ).order_by(
            func.count(func.distinct(models.Image.image_id)).desc(),
            Group.name.asc(),
        ).limit(limit).all()

        data = {
            "contribution": contribution_list,
            "characters": character_rank,
            "groups": group_rank,
            "recent_groups": [
                {
                    "group_id": row.id,
                    "name": row.name,
                    "avatar_url": row.avatar_url or "/favicon.ico",
                    "count": row.image_count,
                }
                for row in recent_group_rows
            ],
            "recent_days": 30,
        }
        _RANKINGS_CACHE.update({
            "key": (limit, group_id),
            "expires_at": time.time() + 60,
            "data": data,
        })
        return data
