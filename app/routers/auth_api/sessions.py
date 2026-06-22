from fastapi import APIRouter, HTTPException, Request, Response
from datetime import date

from ... import schemas
from ...database import get_db_context
from ...models import User, UserRole, GuestLimit
from ...security.tickets import consume_login_ticket
from ...config import settings
from ..auth import (
    GUEST_DAILY_LIMIT,
    GUEST_SESSION_TIMEOUT,
    USER_SESSION_TIMEOUT,
    cleanup_expired_sessions,
    create_session,
    delete_session,
    fetch_qq_info,
    get_client_ip,
    get_session,
    init_root_user,
    ROOT_QQ,
)

router = APIRouter()


def _is_debug_loopback(client_ip: str) -> bool:
    normalized = (client_ip or "").strip().lower()
    compact = normalized.replace(".", "").replace(":", "")
    return normalized in {"127.0.0.1", "::1", "localhost"} or compact == "127001"


@router.post("/login")
async def login(login_data: schemas.UserLogin, request: Request, response: Response):
    """Legacy direct QQ/password login is disabled; use QQ ticket login instead."""
    raise HTTPException(status_code=410, detail="Direct QQ login is disabled. Please use a bot-issued login ticket.")


@router.post("/qq-ticket")
async def login_with_qq_ticket(ticket_data: schemas.QQTicketLogin, request: Request, response: Response):
    """Login through a one-time QQ ticket issued by the trusted bot plugin."""
    with get_db_context() as db:
        cleanup_expired_sessions(db)
        ticket = consume_login_ticket(db, ticket_data.ticket, "login")
        qq_number = ticket.qq_number

        user = db.query(User).filter(User.qq_number == qq_number).first()
        qq_info = await fetch_qq_info(qq_number)

        target_role = UserRole.ROOT.value if qq_number == ROOT_QQ else UserRole.USER.value
        if user:
            if qq_number == ROOT_QQ:
                user.role = UserRole.ROOT.value
            elif user.role == UserRole.ROOT.value:
                user.role = UserRole.USER.value
            user.password_hash = None
            if not user.nickname:
                user.nickname = qq_info["nickname"]
            user.avatar_url = qq_info["avatar_url"]
        else:
            user = User(
                qq_number=qq_number,
                role=target_role,
                password_hash=None,
                nickname=qq_info["nickname"],
                avatar_url=qq_info["avatar_url"],
            )
            db.add(user)
            db.commit()
            db.refresh(user)

        session_id = create_session(db, user, timeout=USER_SESSION_TIMEOUT)
        response.set_cookie(
            key="session_id",
            value=session_id,
            httponly=True,
            max_age=USER_SESSION_TIMEOUT,
            samesite="Lax",
            secure=settings.SESSION_COOKIE_SECURE,
        )

        return {
            "message": "Login successful",
            "redirect_path": ticket.redirect_path or "/",
            "user": schemas.UserInfo.model_validate(user),
        }


@router.post("/guest")
async def guest_login(request: Request, response: Response):
    """游客登录"""
    client_ip = get_client_ip(request)
    
    with get_db_context() as db:
        # 清理过期session
        cleanup_expired_sessions(db)

        if settings.DEBUG and _is_debug_loopback(client_ip):
            root_user = init_root_user(db)
            session_id = create_session(db, root_user, timeout=USER_SESSION_TIMEOUT)
            response.set_cookie(
                key="session_id",
                value=session_id,
                httponly=True,
                max_age=USER_SESSION_TIMEOUT,
                samesite="Lax",
                secure=settings.SESSION_COOKIE_SECURE,
            )

            return {
                "message": "已进入本机调试账号",
                "is_guest": False,
                "debug_login": True,
                "user": schemas.UserInfo.model_validate(root_user),
            }

        # 创建持久化游客会话
        session_id = create_session(db, None, guest_ip=client_ip, timeout=GUEST_SESSION_TIMEOUT)
        response.set_cookie(
            key="session_id",
            value=session_id,
            httponly=True,
            max_age=GUEST_SESSION_TIMEOUT,
            samesite="Lax",
            secure=settings.SESSION_COOKIE_SECURE,
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
    """Password login is disabled; QQ ticket identity is the only login method."""
    raise HTTPException(status_code=410, detail="Password login is disabled")


@router.get("/check-admin")
async def check_if_admin(qq: str):
    """Legacy admin probing endpoint is disabled after QQ ticket login migration."""
    raise HTTPException(status_code=410, detail="Admin probing is disabled")


@router.get("/guest-limit")
async def get_guest_limit(request: Request):
    """获取游客操作限制"""
    session_id = request.cookies.get("session_id")
    if not session_id:
        raise HTTPException(status_code=401, detail="未登录")
    
    with get_db_context() as db:
        session = get_session(db, session_id)
        if not session or not session["is_guest"]:
            return {"is_guest": False}

        client_ip = session["guest_ip"]
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
