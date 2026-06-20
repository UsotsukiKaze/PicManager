from fastapi import APIRouter, HTTPException, Request
from collections import Counter
from datetime import datetime, date
from typing import List
import json
import os

from ... import schemas
from ...database import get_db_context
from ...models import PendingRequest, GuestLimit, RequestStatus, User, Group, Character
from ..auth import GUEST_DAILY_LIMIT, get_current_session, get_session

router = APIRouter()


@router.get("/my-requests", response_model=List[schemas.PendingRequestInfo])
async def get_my_requests(request: Request):
    """获取当前用户提交的审核请求"""
    session_id = request.cookies.get("session_id")
    if not session_id:
        raise HTTPException(status_code=401, detail="未登录")

    with get_db_context() as db:
        session = get_session(db, session_id)
        if not session or session["is_guest"]:
            raise HTTPException(status_code=403, detail="游客不开放")

        user = db.query(User).filter(User.id == session["user_id"]).first()
        if not user:
            raise HTTPException(status_code=401, detail="用户不存在")

        requests = db.query(PendingRequest).filter(
            PendingRequest.user_id == user.id
        ).order_by(PendingRequest.created_at.desc()).all()

        result = []
        for req in requests:
            item = {
                "id": req.id,
                "request_type": req.request_type,
                "status": req.status,
                "user_qq": user.qq_number,
                "user_nickname": user.nickname,
                "user_avatar": user.avatar_url,
                "guest_ip": None,
                "image_id": req.image_id,
                "image_data": json.loads(req.image_data) if req.image_data else None,
                "temp_file_path": req.temp_file_path,
                "original_filename": req.original_filename,
                "rejection_reason": req.rejection_reason,
                "group_info": None,
                "character_names": None,
                "character_info": None,
                "original_image": None,
                "original_group": None,
                "original_character": None,
                "created_at": req.created_at,
                "reviewed_at": req.reviewed_at
            }

            if item["image_data"]:
                image_data = item["image_data"]
                if image_data.get("group_id"):
                    group = db.query(Group).filter(Group.id == image_data["group_id"]).first()
                    if group:
                        item["group_info"] = {"id": group.id, "name": group.name}
                if image_data.get("character_ids"):
                    characters = db.query(Character).filter(
                        Character.id.in_(image_data["character_ids"])
                    ).all()
                    if characters:
                        item["character_names"] = [ch.name for ch in characters]

            result.append(schemas.PendingRequestInfo(**item))

        return result


@router.delete("/pending/{request_id}")
async def cancel_my_request(request_id: int, request: Request):
    """撤销本人待审核请求"""
    session_id = request.cookies.get("session_id")
    if not session_id:
        raise HTTPException(status_code=401, detail="未登录")

    with get_db_context() as db:
        session = get_session(db, session_id)
        if not session or session["is_guest"]:
            raise HTTPException(status_code=403, detail="游客不开放")

        pending_req = db.query(PendingRequest).filter(
            PendingRequest.id == request_id,
            PendingRequest.user_id == session["user_id"]
        ).first()

        if not pending_req:
            raise HTTPException(status_code=404, detail="请求不存在")

        if pending_req.status != RequestStatus.PENDING.value:
            raise HTTPException(status_code=400, detail="请求已处理，无法撤销")

        if pending_req.request_type == "add" and pending_req.temp_file_path:
            try:
                if os.path.exists(pending_req.temp_file_path):
                    os.unlink(pending_req.temp_file_path)
            except Exception:
                pass

        db.delete(pending_req)
        db.commit()
        return {"message": "请求已撤销"}


@router.get("/notifications")
async def get_notifications(request: Request):
    """检查是否有新的审核结果"""
    session_id = request.cookies.get("session_id")
    if not session_id:
        raise HTTPException(status_code=401, detail="未登录")

    with get_db_context() as db:
        session = get_session(db, session_id)
        if not session or session["is_guest"]:
            return {"approved": 0, "rejected": 0}

        user = db.query(User).filter(User.id == session["user_id"]).first()
        if not user:
            raise HTTPException(status_code=401, detail="用户不存在")

        last_notice_at = user.last_notice_at or datetime.utcnow()
        approved = db.query(PendingRequest).filter(
            PendingRequest.user_id == user.id,
            PendingRequest.status == RequestStatus.APPROVED.value,
            PendingRequest.reviewed_at != None,
            PendingRequest.reviewed_at > last_notice_at
        ).count()
        rejected = db.query(PendingRequest).filter(
            PendingRequest.user_id == user.id,
            PendingRequest.status == RequestStatus.REJECTED.value,
            PendingRequest.reviewed_at != None,
            PendingRequest.reviewed_at > last_notice_at
        ).count()

        user.last_notice_at = datetime.utcnow()
        db.commit()

        return {"approved": approved, "rejected": rejected}


@router.get("/profile-stats")
async def get_profile_stats(request: Request):
    """获取个人贡献与偏好统计（游客不可用）"""
    session_id = request.cookies.get("session_id")
    if not session_id:
        raise HTTPException(status_code=401, detail="未登录")

    with get_db_context() as db:
        session = get_session(db, session_id)
        if not session:
            raise HTTPException(status_code=401, detail="会话已过期")

        if session["is_guest"]:
            raise HTTPException(status_code=403, detail="游客不开放")

        user = db.query(User).filter(User.id == session["user_id"]).first()
        if not user:
            raise HTTPException(status_code=401, detail="用户不存在")

        user_requests = db.query(PendingRequest).filter(
            PendingRequest.user_id == user.id
        ).all()

        total_submissions = len(user_requests)
        approved_requests = [
            req for req in user_requests
            if req.status == RequestStatus.APPROVED.value
        ]

        approved_total = len(approved_requests)
        approved_counts = Counter(req.request_type for req in approved_requests)

        approved_add = approved_counts.get("add", 0)
        approved_edit = approved_counts.get("edit", 0)
        approved_delete = approved_counts.get("delete", 0)
        approved_group_add = approved_counts.get("group_add", 0)
        approved_group_edit = approved_counts.get("group_edit", 0)
        approved_group_delete = approved_counts.get("group_delete", 0)
        approved_character_add = approved_counts.get("character_add", 0)
        approved_character_edit = approved_counts.get("character_edit", 0)
        approved_character_delete = approved_counts.get("character_delete", 0)

        weights = {
            "add": 3,
            "edit": 1
        }

        contribution_score = sum(
            approved_counts.get(key, 0) * weight
            for key, weight in weights.items()
        )
        contribution_target = 200
        contribution_percent = int(round(contribution_score / contribution_target * 100)) if contribution_target else 0

        # 偏好统计（仅统计审核通过的添加请求）
        group_counter = Counter()
        character_counter = Counter()
        missing_group_entries = []

        for req in approved_requests:
            if req.request_type != "add" or not req.image_data:
                continue
            try:
                data = json.loads(req.image_data)
            except Exception:
                continue

            group_id = data.get("group_id")
            if group_id:
                try:
                    group_counter[int(group_id)] += 1
                except (TypeError, ValueError):
                    pass

            character_ids = data.get("character_ids") or []
            if isinstance(character_ids, list):
                for cid in character_ids:
                    try:
                        character_counter[int(cid)] += 1
                    except (TypeError, ValueError):
                        continue

                # 如果缺少group_id，后续通过角色分组回填
                if not group_id and character_ids:
                    missing_group_entries.append(character_ids)

        # 通过角色分组回填缺失的分组偏好
        if missing_group_entries:
            missing_character_ids = {
                int(cid)
                for entry in missing_group_entries
                for cid in entry
                if isinstance(cid, (int, str)) and str(cid).isdigit()
            }
            if missing_character_ids:
                characters = db.query(Character).filter(Character.id.in_(missing_character_ids)).all()
                character_group_map = {c.id: c.group_id for c in characters}

                for entry in missing_group_entries:
                    # 取第一个有效角色的分组作为本次上传分组
                    group_id = None
                    for cid in entry:
                        try:
                            cid_int = int(cid)
                        except (TypeError, ValueError):
                            continue
                        group_id = character_group_map.get(cid_int)
                        if group_id:
                            break
                    if group_id:
                        group_counter[int(group_id)] += 1

        group_ids = list(group_counter.keys())
        character_ids = list(character_counter.keys())

        group_map = {}
        if group_ids:
            groups = db.query(Group).filter(Group.id.in_(group_ids)).all()
            group_map = {group.id: group.name for group in groups}

        character_map = {}
        if character_ids:
            characters = db.query(Character).filter(Character.id.in_(character_ids)).all()
            character_map = {character.id: character.name for character in characters}

        group_list = [
            {"id": gid, "name": group_map.get(gid, f"分组 {gid}"), "count": count}
            for gid, count in group_counter.items()
        ]
        group_list.sort(key=lambda item: item["count"], reverse=True)
        group_list = group_list[:5]

        character_list = [
            {"id": cid, "name": character_map.get(cid, f"角色 {cid}"), "count": count}
            for cid, count in character_counter.items()
        ]
        character_list.sort(key=lambda item: item["count"], reverse=True)
        character_list = character_list[:5]

        return {
            "total_submissions": total_submissions,
            "approved_total": approved_total,
            "approved_add": approved_add,
            "approved_edit": approved_edit,
            "approved_delete": approved_delete,
            "approved_group_add": approved_group_add,
            "approved_group_edit": approved_group_edit,
            "approved_group_delete": approved_group_delete,
            "approved_character_add": approved_character_add,
            "approved_character_edit": approved_character_edit,
            "approved_character_delete": approved_character_delete,
            "contribution": {
                "score": contribution_score,
                "percent": contribution_percent
            },
            "preferences": {
                "groups": group_list,
                "characters": character_list,
                "total_group": sum(group_counter.values()),
                "total_character": sum(character_counter.values())
            }
        }


@router.post("/set-nickname")
async def set_nickname(nickname_data: schemas.SetNickname, request: Request):
    """手动设置用户昵称"""
    with get_db_context() as db:
        session = get_current_session(request, db)
        if not session or session["is_guest"]:
            raise HTTPException(status_code=401, detail="需要登录")
        
        user = db.query(User).filter(User.id == session["user_id"]).first()
        if not user:
            raise HTTPException(status_code=401, detail="用户不存在")
        
        # 验证昵称长度
        nickname = nickname_data.nickname.strip()
        if not nickname:
            raise HTTPException(status_code=400, detail="昵称不能为空")
        if len(nickname) > 50:
            raise HTTPException(status_code=400, detail="昵称长度不能超过50字符")
        
        user.nickname = nickname
        db.commit()
        
        return {
            "message": f"昵称已更新为: {nickname}",
            "user": schemas.UserInfo.model_validate(user)
        }
