from fastapi import APIRouter, HTTPException, Request, Response
from sqlalchemy.orm import Session
from typing import Optional
from collections import Counter
from datetime import datetime, date, timedelta
from typing import List
import os
import hashlib
import json
import httpx
import uuid

from ..database import get_db_context
from ..models import User, UserRole, PendingRequest, GuestLimit, RequestStatus, UserSession, Group, Character
from .. import schemas
from ..logger import log_info, log_success, log_error

router = APIRouter()

# Root账户配置
ROOT_QQ = "1356890337"
ROOT_DEFAULT_PASSWORD = "root"
ADMIN_DEFAULT_PASSWORD = "admin"
GUEST_DAILY_LIMIT = 5

# Session过期时间配置（秒）
USER_SESSION_TIMEOUT = 86400 * 7  # 登录用户7天
GUEST_SESSION_TIMEOUT = 86400  # 游客1天

def hash_password(password: str) -> str:
    """简单的密码哈希"""
    return hashlib.sha256(password.encode()).hexdigest()

def verify_password(password: str, password_hash: str) -> bool:
    """验证密码"""
    return hash_password(password) == password_hash

def init_root_user(db: Session):
    """初始化root用户"""
    root_user = db.query(User).filter(User.qq_number == ROOT_QQ).first()
    if not root_user:
        root_user = User(
            qq_number=ROOT_QQ,
            role=UserRole.ROOT.value,
            password_hash=hash_password(ROOT_DEFAULT_PASSWORD)
        )
        db.add(root_user)
        db.commit()
        db.refresh(root_user)
    elif root_user.role != UserRole.ROOT.value:
        # 确保该QQ号是root
        root_user.role = UserRole.ROOT.value
        if not root_user.password_hash:
            root_user.password_hash = hash_password(ROOT_DEFAULT_PASSWORD)
        db.commit()
    return root_user

async def fetch_qq_info(qq_number: str) -> dict:
    """从QQ获取头像和昵称"""
    try:
        # 使用QQ头像API
        avatar_url = f"https://q1.qlogo.cn/g?b=qq&nk={qq_number}&s=640"
        
        # 尝试获取昵称（使用多个备选API）
        nickname = None
        
        # 请求头配置
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
        }

        log_info(f"拉取QQ信息: {qq_number}")
        
        try:
            async with httpx.AsyncClient(timeout=5.0, verify=False) as client:
                # 方案1: 尝试 qq.api.360.cn
                try:
                    resp = await client.get(
                        f"https://qq.api.360.cn/qq/qqcheck",
                        params={"qq": qq_number},
                        headers=headers
                    )
                    if resp.status_code == 200:
                        data = resp.json()
                        if data.get("result") == 0:
                            nickname = data.get("name")
                            if nickname:
                                log_success("QQ昵称获取成功: qq.api.360.cn")
                                return {
                                    "avatar_url": avatar_url,
                                    "nickname": nickname
                                }
                except Exception as e:
                    pass
                
                # 方案2: 尝试 tenapi API
                if not nickname:
                    try:
                        resp = await client.get(
                            "https://api.tenapi.cn/qq/",
                            params={"qq": qq_number},
                            headers=headers,
                            timeout=5.0
                        )
                        if resp.status_code == 200:
                            data = resp.json()
                            if data.get("code") == 200:
                                nickname = data.get("data", {}).get("name")
                                if nickname:
                                    log_success("QQ昵称获取成功: tenapi.cn")
                                    return {
                                        "avatar_url": avatar_url,
                                        "nickname": nickname
                                    }
                    except Exception as e:
                        pass
                
                # 方案3: 尝试 alapi.net
                if not nickname:
                    try:
                        resp = await client.get(
                            f"https://api.alapi.cn/api/qq",
                            params={"qq": qq_number},
                            headers=headers,
                            timeout=5.0
                        )
                        if resp.status_code == 200:
                            data = resp.json()
                            if data.get("code") == 0:
                                nickname = data.get("data", {}).get("name")
                                if nickname:
                                    log_success("QQ昵称获取成功: alapi.cn")
                                    return {
                                        "avatar_url": avatar_url,
                                        "nickname": nickname
                                    }
                    except Exception as e:
                        pass
        except:
            pass
        
        # 如果所有API都失败，返回默认昵称
        log_error("QQ昵称获取失败，使用默认昵称")
        return {
            "avatar_url": avatar_url,
            "nickname": f"用户{qq_number[-4:]}"
        }
    except:
        log_error("QQ昵称获取异常，使用默认昵称")
        return {
            "avatar_url": f"https://q1.qlogo.cn/g?b=qq&nk={qq_number}&s=640",
            "nickname": f"用户{qq_number[-4:]}"
        }

def get_client_ip(request: Request) -> str:
    """获取客户端IP"""
    forwarded = request.headers.get("X-Forwarded-For")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


def cleanup_expired_sessions(db: Session):
    """清理过期的session"""
    now = datetime.utcnow()
    expired = db.query(UserSession).filter(UserSession.expires_at <= now).delete()
    if expired > 0:
        db.commit()
    return expired


def create_session(db: Session, user: Optional[User], guest_ip: Optional[str] = None, timeout: int = USER_SESSION_TIMEOUT) -> str:
    """在数据库中创建会话"""
    session_id = str(uuid.uuid4())
    expires_at = datetime.utcnow() + timedelta(seconds=timeout)
    
    session = UserSession(
        session_id=session_id,
        user_id=user.id if user else None,
        guest_ip=guest_ip,
        is_guest="true" if user is None else "false",
        created_at=datetime.utcnow(),
        last_activity=datetime.utcnow(),
        expires_at=expires_at
    )
    
    db.add(session)
    db.commit()
    return session_id


def get_session(db: Session, session_id: str) -> Optional[dict]:
    """从数据库获取会话"""
    session = db.query(UserSession).filter(UserSession.session_id == session_id).first()
    
    if not session:
        return None
    
    # 检查是否过期
    if session.expires_at <= datetime.utcnow():
        db.delete(session)
        db.commit()
        return None
    
    # 更新最后活动时间
    session.last_activity = datetime.utcnow()
    db.commit()
    
    return {
        "user_id": session.user_id,
        "is_guest": session.is_guest == "true",
        "guest_ip": session.guest_ip,
        "created_at": session.created_at,
        "session_id": session.session_id
    }


def delete_session(db: Session, session_id: str):
    """从数据库删除会话"""
    session = db.query(UserSession).filter(UserSession.session_id == session_id).first()
    if session:
        db.delete(session)
        db.commit()


@router.post("/login")
async def login(login_data: schemas.UserLogin, request: Request, response: Response):
    """用户登录"""
    with get_db_context() as db:
        # 初始化root用户
        init_root_user(db)
        
        # 清理过期session
        cleanup_expired_sessions(db)
        
        qq_number = login_data.qq_number.strip()
        
        # 查找用户
        user = db.query(User).filter(User.qq_number == qq_number).first()
        
        if user:
            # 已存在用户
            if user.role in [UserRole.ROOT.value, UserRole.ADMIN.value]:
                # 管理员需要密码
                if not login_data.password:
                    raise HTTPException(status_code=400, detail="管理员登录需要密码")
                if not verify_password(login_data.password, user.password_hash):
                    raise HTTPException(status_code=401, detail="密码错误")
            
            # 更新用户头像（昵称以用户手动设置为准）
            qq_info = await fetch_qq_info(qq_number)
            if not user.nickname:
                user.nickname = qq_info["nickname"]
            user.avatar_url = qq_info["avatar_url"]
            db.commit()
        else:
            # 新用户，创建为普通用户
            qq_info = await fetch_qq_info(qq_number)
            user = User(
                qq_number=qq_number,
                role=UserRole.USER.value,
                nickname=qq_info["nickname"],
                avatar_url=qq_info["avatar_url"]
            )
            db.add(user)
            db.commit()
            db.refresh(user)
        
        # 创建持久化会话
        session_id = create_session(db, user, timeout=USER_SESSION_TIMEOUT)
        response.set_cookie(
            key="session_id",
            value=session_id,
            httponly=True,
            max_age=USER_SESSION_TIMEOUT,
            samesite="Lax"
        )
        
        return {
            "message": "登录成功",
            "user": schemas.UserInfo.model_validate(user)
        }


@router.post("/guest")
async def guest_login(request: Request, response: Response):
    """游客登录"""
    client_ip = get_client_ip(request)
    
    with get_db_context() as db:
        # 清理过期session
        cleanup_expired_sessions(db)
        
        # 创建持久化游客会话
        session_id = create_session(db, None, guest_ip=client_ip, timeout=GUEST_SESSION_TIMEOUT)
        response.set_cookie(
            key="session_id",
            value=session_id,
            httponly=True,
            max_age=GUEST_SESSION_TIMEOUT,
            samesite="Lax"
        )
        
        # 获取今日剩余操作次数
        today = date.today()
        limit_record = db.query(GuestLimit).filter(
            GuestLimit.ip_address == client_ip,
            GuestLimit.date == today
        ).first()
        
        remaining = GUEST_DAILY_LIMIT - (limit_record.operation_count if limit_record else 0)
    
    return {
        "message": "游客登录成功",
        "is_guest": True,
        "guest_ip": client_ip,
        "remaining_operations": max(0, remaining)
    }


@router.get("/me")
async def get_current_user(request: Request):
    """获取当前用户信息"""
    session_id = request.cookies.get("session_id")
    if not session_id:
        raise HTTPException(status_code=401, detail="未登录")
    
    with get_db_context() as db:
        session = get_session(db, session_id)
        if not session:
            raise HTTPException(status_code=401, detail="会话已过期")
        
        if session["is_guest"]:
            # 游客
            client_ip = session["guest_ip"]
            today = date.today()
            limit_record = db.query(GuestLimit).filter(
                GuestLimit.ip_address == client_ip,
                GuestLimit.date == today
            ).first()
            remaining = GUEST_DAILY_LIMIT - (limit_record.operation_count if limit_record else 0)
            
            return {
                "is_guest": True,
                "guest_ip": client_ip,
                "remaining_operations": max(0, remaining),
                "daily_limit": GUEST_DAILY_LIMIT
            }
        else:
            # 已登录用户
            user = db.query(User).filter(User.id == session["user_id"]).first()
            if not user:
                raise HTTPException(status_code=401, detail="用户不存在")
            return {
                "is_guest": False,
                "user": schemas.UserInfo.model_validate(user)
            }


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
            "edit": 1,
            "delete": 1,
            "group_add": 2,
            "group_edit": 1,
            "group_delete": 1,
            "character_add": 2,
            "character_edit": 1,
            "character_delete": 1
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


@router.post("/logout")
async def logout(request: Request, response: Response):
    """登出"""
    session_id = request.cookies.get("session_id")
    if session_id:
        with get_db_context() as db:
            delete_session(db, session_id)
    
    response.delete_cookie("session_id")
    return {"message": "登出成功"}


@router.put("/password")
async def change_password(password_data: schemas.ChangePassword, request: Request):
    """修改密码（仅管理员）"""
    session_id = request.cookies.get("session_id")
    if not session_id:
        raise HTTPException(status_code=401, detail="未登录")
    
    with get_db_context() as db:
        session = get_session(db, session_id)
        if not session or session["is_guest"]:
            raise HTTPException(status_code=401, detail="需要登录账户")
        
        user = db.query(User).filter(User.id == session["user_id"]).first()
        if not user:
            raise HTTPException(status_code=401, detail="用户不存在")
        
        if user.role not in [UserRole.ROOT.value, UserRole.ADMIN.value]:
            raise HTTPException(status_code=403, detail="只有管理员可以修改密码")
        
        if not verify_password(password_data.old_password, user.password_hash):
            raise HTTPException(status_code=400, detail="原密码错误")
        
        user.password_hash = hash_password(password_data.new_password)
        db.commit()
        
        return {"message": "密码修改成功"}


@router.get("/check-admin")
async def check_if_admin(qq: str):
    """检查QQ号是否是管理员（用于登录页显示密码框）"""
    with get_db_context() as db:
        # 初始化root用户
        init_root_user(db)
        
        user = db.query(User).filter(User.qq_number == qq).first()
        if user and user.role in [UserRole.ROOT.value, UserRole.ADMIN.value]:
            return {"is_admin": True}
        return {"is_admin": False}


@router.get("/guest-limit")
async def get_guest_limit(request: Request):
    """获取游客操作限制"""
    session_id = request.cookies.get("session_id")
    if not session_id:
        raise HTTPException(status_code=401, detail="未登录")
    
    session = get_session(session_id)
    if not session or not session["is_guest"]:
        return {"is_guest": False}
    
    client_ip = session["guest_ip"]
    with get_db_context() as db:
        today = date.today()
        limit_record = db.query(GuestLimit).filter(
            GuestLimit.ip_address == client_ip,
            GuestLimit.date == today
        ).first()
        
        remaining = GUEST_DAILY_LIMIT - (limit_record.operation_count if limit_record else 0)
    
    return {
        "is_guest": True,
        "remaining_operations": max(0, remaining),
        "daily_limit": GUEST_DAILY_LIMIT
    }


def check_guest_limit(db: Session, ip_address: str) -> bool:
    """检查游客是否还有操作次数，如果有则消耗一次"""
    today = date.today()
    limit_record = db.query(GuestLimit).filter(
        GuestLimit.ip_address == ip_address,
        GuestLimit.date == today
    ).first()
    
    if not limit_record:
        # 创建新记录
        limit_record = GuestLimit(
            ip_address=ip_address,
            date=today,
            operation_count=1
        )
        db.add(limit_record)
        return True
    
    if limit_record.operation_count >= GUEST_DAILY_LIMIT:
        return False
    
    limit_record.operation_count += 1
    return True


def get_current_session(request: Request, db: Optional[Session] = None) -> dict:
    """获取当前会话信息的辅助函数"""
    session_id = request.cookies.get("session_id")
    if not session_id:
        return None
    
    # 如果没有传入db，则创建一个新的context
    if db is None:
        with get_db_context() as db:
            return get_session(db, session_id)
    else:
        return get_session(db, session_id)


def is_admin_or_root(request: Request) -> bool:
    """检查是否是管理员或root"""
    with get_db_context() as db:
        session = get_current_session(request, db)
        if not session or session["is_guest"]:
            return False
        
        user = db.query(User).filter(User.id == session["user_id"]).first()
        return user and user.role in [UserRole.ROOT.value, UserRole.ADMIN.value]
