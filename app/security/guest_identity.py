"""Signed, persistent identities for anonymous visitors."""

from __future__ import annotations

import hashlib
import hmac
import secrets

from ..config import settings


GUEST_IDENTITY_COOKIE = "guest_identity"
GUEST_IDENTITY_MAX_AGE = 86400 * 365


def _signature(payload: str) -> str:
    return hmac.new(
        settings.SECRET_KEY.encode("utf-8"),
        payload.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()


def create_guest_identity(number: int | None = None) -> tuple[str, str]:
    """Create a signed cookie value and its public display name."""
    number = number if number is not None else secrets.randbelow(9000) + 1000
    if not 1000 <= number <= 9999:
        raise ValueError("guest number must contain four digits")
    payload = f"{number}.{secrets.token_urlsafe(18)}"
    return f"{payload}.{_signature(payload)}", f"游客#{number:04d}"


def read_guest_identity(cookie_value: str | None) -> str | None:
    """Validate a guest cookie and return its public display name."""
    if not cookie_value:
        return None
    try:
        number_text, nonce, supplied_signature = cookie_value.split(".", 2)
        number = int(number_text)
    except (TypeError, ValueError):
        return None
    if not 1000 <= number <= 9999 or not nonce:
        return None
    payload = f"{number_text}.{nonce}"
    if not hmac.compare_digest(supplied_signature, _signature(payload)):
        return None
    return f"游客#{number:04d}"
