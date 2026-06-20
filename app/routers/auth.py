"""Authentication/session helper functions.

HTTP routes are split into sessions.py and profile.py; this module keeps shared
helpers used by route modules and permission checks.
"""

from fastapi import HTTPException, Request
from sqlalchemy.orm import Session
from typing import Optional
from datetime import datetime, date, timedelta
import os
import httpx
import uuid

from ..database import get_db_context
from ..models import User, UserRole, GuestLimit, UserSession
from ..logger import log_info, log_success, log_error
from ..config import settings


# Root账户配置
ROOT_QQ = settings.ROOT_QQ
GUEST_DAILY_LIMIT = 5

# Session过期时间配置（秒）
USER_SESSION_TIMEOUT = 86400 * 7  # 登录用户7天
GUEST_SESSION_TIMEOUT = 86400  # 游客1天

def init_root_user(db: Session):
    """初始化root用户"""
    root_user = db.query(User).filter(User.qq_number == ROOT_QQ).first()
    if not root_user:
        root_user = User(
            qq_number=ROOT_QQ,
            role=UserRole.ROOT.value,
            password_hash=None,
        )
        db.add(root_user)
        db.commit()
        db.refresh(root_user)
    elif root_user.role != UserRole.ROOT.value or root_user.password_hash:
        # Ensure the configured QQ is the only root identity. Password login is disabled.
        root_user.role = UserRole.ROOT.value
        root_user.password_hash = None
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
            async with httpx.AsyncClient(timeout=5.0) as client:
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
    if settings.TRUST_PROXY_HEADERS and forwarded:
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
        if not user:
            return False
        if user.role == UserRole.ROOT.value:
            return user.qq_number == ROOT_QQ
        return user.role == UserRole.ADMIN.value
