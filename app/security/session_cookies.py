from __future__ import annotations

from fastapi import Request, Response

from ..config import Settings, settings
from .lan_debug import is_lan_debug_request


COOKIE_PATH = "/"
COOKIE_SAMESITE = "lax"


def auth_cookie_secure(request: Request, config: Settings = settings) -> bool:
    """Keep production cookies secure; relax only for an explicit HTTP LAN debug host."""
    if is_lan_debug_request(request, config):
        return False
    return bool(config.SESSION_COOKIE_SECURE)


def auth_cookie_domain(request: Request, config: Settings = settings) -> str | None:
    # A production domain cookie is invalid for an IP-address LAN origin.
    if is_lan_debug_request(request, config):
        return None
    return str(config.SESSION_COOKIE_DOMAIN or "").strip() or None


def set_auth_cookie(
    response: Response,
    request: Request,
    *,
    key: str,
    value: str,
    max_age: int,
    config: Settings = settings,
) -> None:
    response.set_cookie(
        key=key,
        value=value,
        httponly=True,
        max_age=max_age,
        path=COOKIE_PATH,
        samesite=COOKIE_SAMESITE,
        secure=auth_cookie_secure(request, config),
        domain=auth_cookie_domain(request, config),
    )


def delete_auth_cookie(
    response: Response,
    request: Request,
    *,
    key: str,
    config: Settings = settings,
) -> None:
    response.delete_cookie(
        key=key,
        path=COOKIE_PATH,
        domain=auth_cookie_domain(request, config),
        secure=auth_cookie_secure(request, config),
        httponly=True,
        samesite=COOKIE_SAMESITE,
    )
