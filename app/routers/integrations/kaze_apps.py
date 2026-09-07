from __future__ import annotations

import hmac
import ipaddress

from fastapi import APIRouter, Header, HTTPException, Request
from pydantic import BaseModel, Field

from ...config import settings
from ...database import get_db_context
from ...models import User, UserRole
from ..auth import get_session


router = APIRouter(tags=["kaze-apps"])


class RootSessionCheck(BaseModel):
    session_id: str = Field(min_length=20, max_length=128)


def _require_internal_request(request: Request, authorization: str | None) -> None:
    configured = str(settings.KAZE_APPS_INTERNAL_TOKEN or "").strip()
    if not configured:
        raise HTTPException(status_code=503, detail="KazeApps internal authentication is not configured")

    client_host = request.client.host if request.client else ""
    try:
        is_loopback = ipaddress.ip_address(client_host).is_loopback
    except ValueError:
        is_loopback = False
    if not is_loopback:
        raise HTTPException(status_code=403, detail="Loopback access required")

    scheme, _, token = str(authorization or "").partition(" ")
    if scheme.lower() != "bearer" or not hmac.compare_digest(token, configured):
        raise HTTPException(status_code=403, detail="Invalid internal token")


@router.post("/root-session")
def verify_root_session(
    payload: RootSessionCheck,
    request: Request,
    authorization: str | None = Header(default=None),
):
    """Validate a shared browser session for KazeApps over the loopback interface."""
    _require_internal_request(request, authorization)
    with get_db_context() as db:
        session = get_session(db, payload.session_id)
        if not session or session.get("is_guest"):
            return {"authenticated": False, "isRoot": False}
        user = db.query(User).filter(User.id == session["user_id"]).first()
        is_root = bool(
            user
            and user.role == UserRole.ROOT.value
            and user.qq_number == settings.ROOT_QQ
        )
        return {
            "authenticated": bool(user),
            "isRoot": is_root,
            "nickname": (user.nickname or "拈风") if is_root else None,
        }
