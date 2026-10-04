"""Eligibility shared by local Root debug login and its session cookies."""
from ipaddress import ip_address

from fastapi import Request

from ..config import Settings, settings


def is_local_debug_root_request(request: Request, config: Settings = settings) -> bool:
    if not (config.DEBUG and config.DEBUG_GUEST_ROOT) or not request.client:
        return False
    if request.url.hostname not in {"localhost", "127.0.0.1", "::1"}:
        return False
    if any(name in request.headers for name in ("forwarded", "x-forwarded-for", "x-forwarded-host")):
        return False
    try:
        return ip_address(request.client.host).is_loopback
    except ValueError:
        return False
