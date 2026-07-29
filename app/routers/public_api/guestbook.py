from datetime import datetime
from time import monotonic

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from ...database import get_db_context
from ...models import GuestbookMessage, User, UserRole
from ..auth import get_current_session
from ...security.permissions import require_root_user_id
from ...config import settings

router = APIRouter(prefix="/guestbook", tags=["guestbook"])

POST_INTERVAL_SECONDS = 30
_last_post_at: dict[str, float] = {}


class GuestbookMessageCreate(BaseModel):
    nickname: str = Field(min_length=1, max_length=32)
    content: str = Field(min_length=1, max_length=500)


class GuestbookReplyCreate(BaseModel):
    content: str = Field(min_length=1, max_length=500)


def serialize_message(message: GuestbookMessage) -> dict:
    return {
        "id": message.id,
        "nickname": message.nickname,
        "content": message.content,
        "parent_id": message.parent_id,
        "created_at": message.created_at.isoformat() if message.created_at else datetime.utcnow().isoformat(),
    }


def client_address(request: Request) -> str:
    return request.headers.get("cf-connecting-ip") or (request.client.host if request.client else "unknown")


def can_manage_guestbook(request: Request) -> bool:
    with get_db_context() as db:
        session = get_current_session(request, db)
        if not session or session.get("is_guest"):
            return False
        user = db.query(User).filter(User.id == session["user_id"]).first()
        return bool(user and user.role == UserRole.ROOT.value and user.qq_number == settings.ROOT_QQ)


@router.get("")
def list_messages(limit: int = 30):
    safe_limit = max(1, min(limit, 100))
    with get_db_context() as db:
        messages = (
            db.query(GuestbookMessage)
            .filter(GuestbookMessage.parent_id.is_(None))
            .order_by(GuestbookMessage.created_at.desc(), GuestbookMessage.id.desc())
            .limit(safe_limit)
            .all()
        )
        message_ids = [message.id for message in messages]
        replies = []
        if message_ids:
            replies = (
                db.query(GuestbookMessage)
                .filter(GuestbookMessage.parent_id.in_(message_ids))
                .order_by(GuestbookMessage.created_at.asc(), GuestbookMessage.id.asc())
                .all()
            )
        grouped_replies: dict[int, list[dict]] = {message_id: [] for message_id in message_ids}
        for reply in replies:
            grouped_replies.setdefault(reply.parent_id, []).append(serialize_message(reply))
        result = []
        for message in messages:
            item = serialize_message(message)
            item["replies"] = grouped_replies.get(message.id, [])
            result.append(item)
        return {"messages": result}


@router.get("/permissions")
def guestbook_permissions(request: Request):
    return {"can_manage": can_manage_guestbook(request)}


@router.post("", status_code=201)
def create_message(payload: GuestbookMessageCreate, request: Request):
    nickname = payload.nickname.strip()
    content = payload.content.strip()
    if not nickname or not content:
        raise HTTPException(status_code=422, detail="昵称和留言不能为空")

    address = client_address(request)
    now = monotonic()
    if now - _last_post_at.get(address, 0) < POST_INTERVAL_SECONDS:
        raise HTTPException(status_code=429, detail="请稍后再留言")

    with get_db_context() as db:
        message = GuestbookMessage(nickname=nickname, content=content)
        db.add(message)
        db.flush()
        db.refresh(message)
        result = serialize_message(message)

    _last_post_at[address] = now
    return result


@router.post("/{message_id}/replies", status_code=201)
def reply_to_message(message_id: int, payload: GuestbookReplyCreate, request: Request):
    require_root_user_id(request)
    content = payload.content.strip()
    if not content:
        raise HTTPException(status_code=422, detail="回复不能为空")

    with get_db_context() as db:
        parent = db.query(GuestbookMessage).filter(
            GuestbookMessage.id == message_id,
            GuestbookMessage.parent_id.is_(None),
        ).first()
        if not parent:
            raise HTTPException(status_code=404, detail="留言不存在")
        reply = GuestbookMessage(nickname="UsotsukiKaze", content=content, parent_id=parent.id)
        db.add(reply)
        db.flush()
        db.refresh(reply)
        result = serialize_message(reply)
    return result


@router.delete("/{message_id}", status_code=204)
def delete_message(message_id: int, request: Request):
    require_root_user_id(request)
    with get_db_context() as db:
        message = db.query(GuestbookMessage).filter(GuestbookMessage.id == message_id).first()
        if not message:
            raise HTTPException(status_code=404, detail="留言不存在")
        if message.parent_id is None:
            db.query(GuestbookMessage).filter(GuestbookMessage.parent_id == message.id).delete()
        db.delete(message)
