from fastapi import HTTPException, Request

from ..database import get_db_context
from ..models import User, UserRole
from ..routers.auth import get_current_session
from ..config import settings


def require_admin_user_id(request: Request) -> int:
    """Return current user id when the request belongs to an admin or root user."""
    with get_db_context() as db:
        session = get_current_session(request, db)
        if not session or session.get("is_guest"):
            raise HTTPException(status_code=401, detail="Admin login required")

        user = db.query(User).filter(User.id == session["user_id"]).first()
        if not user:
            raise HTTPException(status_code=401, detail="User not found")
        if user.role not in [UserRole.ROOT.value, UserRole.ADMIN.value]:
            raise HTTPException(status_code=403, detail="Admin permission required")
        return user.id


def require_root_user_id(request: Request) -> int:
    """Return current user id when the request belongs to the root user."""
    with get_db_context() as db:
        session = get_current_session(request, db)
        if not session or session.get("is_guest"):
            raise HTTPException(status_code=401, detail="Root login required")

        user = db.query(User).filter(User.id == session["user_id"]).first()
        if not user:
            raise HTTPException(status_code=401, detail="User not found")
        if user.role != UserRole.ROOT.value or user.qq_number != settings.ROOT_QQ:
            raise HTTPException(status_code=403, detail="Root permission required")
        return user.id
