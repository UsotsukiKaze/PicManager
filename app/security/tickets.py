from __future__ import annotations

import hashlib
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta
from urllib.parse import urlencode

from fastapi import HTTPException
from sqlalchemy.orm import Session

from ..config import settings
from ..models import LoginTicket

DEFAULT_TICKET_TTL_SECONDS = 300
ALLOWED_PURPOSES = {"login", "upload", "admin"}


@dataclass
class IssuedTicket:
    ticket: str
    record: LoginTicket


def hash_ticket(ticket: str) -> str:
    return hashlib.sha256(ticket.encode("utf-8")).hexdigest()


def normalize_qq_number(qq_number: str) -> str:
    normalized = (qq_number or "").strip()
    if not normalized.isdigit() or not 5 <= len(normalized) <= 20:
        raise HTTPException(status_code=400, detail="Invalid QQ number")
    return normalized


def normalize_purpose(purpose: str) -> str:
    normalized = (purpose or "login").strip().lower()
    if normalized not in ALLOWED_PURPOSES:
        raise HTTPException(status_code=400, detail="Invalid ticket purpose")
    return normalized


def normalize_redirect_path(redirect_path: str | None) -> str:
    path = (redirect_path or "/").strip() or "/"
    if not path.startswith("/") or path.startswith("//") or "://" in path:
        raise HTTPException(status_code=400, detail="Invalid redirect path")
    return path


def create_login_ticket(
    db: Session,
    qq_number: str,
    purpose: str = "login",
    redirect_path: str | None = "/",
    created_by: str | None = None,
) -> IssuedTicket:
    raw_ticket = secrets.token_urlsafe(32)
    ttl = int(getattr(settings, "LOGIN_TICKET_TTL_SECONDS", DEFAULT_TICKET_TTL_SECONDS))
    record = LoginTicket(
        ticket_hash=hash_ticket(raw_ticket),
        qq_number=normalize_qq_number(qq_number),
        purpose=normalize_purpose(purpose),
        redirect_path=normalize_redirect_path(redirect_path),
        created_by=(created_by or None),
        expires_at=datetime.utcnow() + timedelta(seconds=max(ttl, 30)),
    )
    db.add(record)
    db.flush()
    return IssuedTicket(ticket=raw_ticket, record=record)


def consume_login_ticket(db: Session, ticket: str, purpose: str = "login") -> LoginTicket:
    ticket_hash = hash_ticket((ticket or "").strip())
    record = db.query(LoginTicket).filter(LoginTicket.ticket_hash == ticket_hash).first()
    if not record:
        raise HTTPException(status_code=401, detail="Invalid login ticket")
    if record.used_at is not None:
        raise HTTPException(status_code=401, detail="Login ticket has already been used")
    if record.expires_at <= datetime.utcnow():
        raise HTTPException(status_code=401, detail="Login ticket has expired")
    if record.purpose != normalize_purpose(purpose):
        raise HTTPException(status_code=403, detail="Login ticket purpose mismatch")

    record.used_at = datetime.utcnow()
    db.flush()
    return record


def build_login_url(ticket: str, redirect_path: str | None = None) -> str:
    public_base = getattr(settings, "PUBLIC_BASE_URL", "").rstrip("/")
    query = {"ticket": ticket}
    if redirect_path:
        query["redirect"] = redirect_path
    path = f"/login?{urlencode(query)}"
    return f"{public_base}{path}" if public_base else path
