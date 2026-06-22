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
import time

router = APIRouter()

_RANKINGS_CACHE = {"key": None, "expires_at": 0.0, "data": None}


@router.get("/rankings")
def get_rankings(limit: int = 10):
    limit = max(1, min(limit, 50))
    now = time.time()
    if (
        _RANKINGS_CACHE["key"] == limit
        and _RANKINGS_CACHE["data"] is not None
        and _RANKINGS_CACHE["expires_at"] > now
    ):
        return _RANKINGS_CACHE["data"]
    """获取贡献榜、角色人气榜、图片人气榜"""
    with get_db_context() as db:
        # 贡献榜（仅登录用户）
        approved_requests = db.query(PendingRequest).filter(
            PendingRequest.user_id.isnot(None),
            PendingRequest.status == RequestStatus.APPROVED.value
        ).all()

        weights = {
            "add": 2,
            "edit": 1
        }

        contribution_map = {}
        for req in approved_requests:
            if not req.user_id:
                continue
            user_score = contribution_map.setdefault(req.user_id, {
                "score": 0,
                "counts": {}
            })
            user_score["score"] += weights.get(req.request_type, 0)

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

        # 角色人气榜（无统计时回退到最新角色）
        character_query_rows = db.query(CharacterQueryCount).order_by(
            CharacterQueryCount.query_count.desc()
        ).limit(limit).all()
        if character_query_rows:
            character_ids = [row.character_id for row in character_query_rows]
            characters = db.query(Character).filter(Character.id.in_(character_ids)).all()
            character_map = {c.id: c for c in characters}

            character_rank = []
            for row in character_query_rows:
                character = character_map.get(row.character_id)
                if not character:
                    continue
                group = db.query(Group).filter(Group.id == character.group_id).first()
                character_rank.append({
                    "character_id": character.id,
                    "name": character.name,
                    "group_name": group.name if group else None,
                    "count": row.query_count
                })
        else:
            latest_characters = db.query(Character).order_by(Character.created_at.desc()).limit(limit).all()
            character_rank = []
            for character in latest_characters:
                group = db.query(Group).filter(Group.id == character.group_id).first()
                character_rank.append({
                    "character_id": character.id,
                    "name": character.name,
                    "group_name": group.name if group else None,
                    "count": 0
                })

        # 图片人气榜（无统计时回退到最新图片）
        image_view_rows = db.query(ImageViewCount).order_by(
            ImageViewCount.view_count.desc()
        ).limit(limit).all()
        if image_view_rows:
            image_ids = [row.image_id for row in image_view_rows]
            images = db.query(models.Image).filter(
                models.Image.image_id.in_(image_ids),
                models.Image.file_status == ImageService.AVAILABLE
            ).all()
            image_map = {img.image_id: img for img in images}

            image_rank = []
            for row in image_view_rows:
                image = image_map.get(row.image_id)
                if not image:
                    continue
                image_rank.append({
                    "image_id": image.image_id,
                    "file_extension": image.file_extension,
                    "file_path": image.file_path,
                    "count": row.view_count
                })
        else:
            latest_images = db.query(models.Image).filter(
                models.Image.file_status == ImageService.AVAILABLE
            ).order_by(
                models.Image.created_at.desc(),
                models.Image.image_id.desc()
            ).limit(limit).all()
            image_rank = [
                {
                    "image_id": image.image_id,
                    "file_extension": image.file_extension,
                    "file_path": image.file_path,
                    "count": 0
                }
                for image in latest_images
            ]

        data = {
            "contribution": contribution_list,
            "characters": character_rank,
            "images": image_rank
        }
        _RANKINGS_CACHE.update({
            "key": limit,
            "expires_at": time.time() + 60,
            "data": data,
        })
        return data
