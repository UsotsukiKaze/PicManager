from __future__ import annotations

import ipaddress
import re
from urllib.parse import urlsplit

from fastapi import Request

from ..config import Settings, settings


_HOST_LABEL = re.compile(r"^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$")


def normalize_exact_host(value: str) -> str:
    """Normalize one exact host while rejecting wildcard and URL-like values."""
    host = str(value or "").strip().lower().rstrip(".")
    if not host or "*" in host or "/" in host or "\\" in host or "://" in host:
        raise RuntimeError(f"Invalid exact host: {value!r}")

    try:
        ipaddress.ip_address(host)
        return host
    except ValueError:
        pass

    if len(host) > 253 or any(not _HOST_LABEL.fullmatch(label) for label in host.split(".")):
        raise RuntimeError(f"Invalid exact host: {value!r}")
    return host


def exact_hosts(value: str, *, setting_name: str) -> list[str]:
    hosts: list[str] = []
    for raw_host in str(value or "").split(","):
        if not raw_host.strip():
            continue
        try:
            host = normalize_exact_host(raw_host)
        except RuntimeError as exc:
            raise RuntimeError(f"{setting_name} must contain exact hosts only") from exc
        if host not in hosts:
            hosts.append(host)
    return hosts


def configured_lan_hosts(config: Settings = settings) -> list[str]:
    if not config.LAN_DEBUG_ENABLED:
        return []
    hosts = exact_hosts(config.LAN_DEBUG_HOSTS, setting_name="LAN_DEBUG_HOSTS")
    if not hosts:
        raise RuntimeError("LAN_DEBUG_HOSTS is required when LAN_DEBUG_ENABLED=true")
    return hosts


def configured_lan_base_url(config: Settings = settings) -> str | None:
    """Return the fixed LAN origin after verifying it belongs to the LAN allowlist."""
    if not config.LAN_DEBUG_ENABLED:
        return None
    raw_url = str(config.LAN_DEBUG_BASE_URL or "").strip()
    if not raw_url:
        return None

    parsed = urlsplit(raw_url)
    if (
        parsed.scheme.lower() != "http"
        or not parsed.hostname
        or parsed.username
        or parsed.password
        or parsed.query
        or parsed.fragment
        or parsed.path not in {"", "/"}
    ):
        raise RuntimeError("LAN_DEBUG_BASE_URL must be a fixed HTTP origin without path, credentials, query, or fragment")

    host = normalize_exact_host(parsed.hostname)
    if host not in configured_lan_hosts(config):
        raise RuntimeError("LAN_DEBUG_BASE_URL host must be listed in LAN_DEBUG_HOSTS")
    try:
        port = parsed.port
    except ValueError as exc:
        raise RuntimeError("LAN_DEBUG_BASE_URL contains an invalid port") from exc

    authority = f"[{host}]" if ":" in host else host
    if port is not None:
        authority = f"{authority}:{port}"
    return f"http://{authority}"


def is_lan_debug_request(request: Request, config: Settings = settings) -> bool:
    if not config.LAN_DEBUG_ENABLED or request.url.scheme.lower() != "http":
        return False
    request_host = request.url.hostname
    if not request_host:
        return False
    try:
        normalized = normalize_exact_host(request_host)
    except RuntimeError:
        return False
    return normalized in configured_lan_hosts(config)
