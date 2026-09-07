from __future__ import annotations

from http import HTTPStatus
from time import perf_counter
from typing import Any, Awaitable, Callable
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit
import re
import sys

LogHook = Callable[[str, str], None]
CallNext = Callable[[Any], Awaitable[Any]]

_COLOR_RESET = "\033[0m"
_COLOR_MUTED = "\033[90m"
_LEVEL_COLORS = {
    "INFO": "\033[94m",
    "SUCCESS": "\033[92m",
    "ERROR": "\033[91m",
}

_SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}
_QUIET_PATH_PREFIXES = ("/static/", "/resource/thumbs/")
_SENSITIVE_QUERY_WORDS = {
    "authorization",
    "credential",
    "credentials",
    "key",
    "password",
    "passwd",
    "pwd",
    "secret",
    "signature",
    "ticket",
    "token",
}
_SENSITIVE_QUERY_NAMES = {
    "auth",
    "authcode",
    "code",
    "session",
    "sessionid",
}
_SENSITIVE_QUERY_SUFFIXES = (
    "authorization",
    "credential",
    "credentials",
    "password",
    "passwd",
    "secret",
    "sessionid",
    "signature",
    "ticket",
    "token",
)


def _default_log_hook(level: str, message: str, detail: str | None = None) -> None:
    """Render only the level prominently; optional context stays muted."""
    color = _LEVEL_COLORS.get(level, _LEVEL_COLORS["INFO"])
    prefix = f"{level}:".ljust(9)
    body = message
    if detail:
        muted_detail = f"{_COLOR_MUTED}{detail}{_COLOR_RESET}"
        body = f"{message}  {muted_detail}" if message else muted_detail
    sys.stdout.write(f"{color}{prefix}{_COLOR_RESET}{body}\n")


_log_hook: LogHook = _default_log_hook


def set_log_hook(hook: LogHook) -> None:
    """替换日志输出，主要用于测试或接入其他日志后端。"""
    global _log_hook
    _log_hook = hook


def _log(level: str, message: str, detail: str | None = None) -> None:
    if detail is not None and _log_hook is _default_log_hook:
        _default_log_hook(level, message, detail)
        return

    plain_message = "  ".join(part for part in (message, detail) if part)
    _log_hook(level, plain_message)


def log_info(message: str) -> None:
    _log("INFO", message)


def log_success(message: str) -> None:
    _log("SUCCESS", message)


def log_error(message: str) -> None:
    _log("ERROR", message)


def _safe_text(value: Any) -> str:
    printable = "".join(character if character.isprintable() else " " for character in str(value))
    return " ".join(printable.split())


def _is_sensitive_query_key(key: str) -> bool:
    separated = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", "_", key)
    parts = [part for part in re.sub(r"[^a-zA-Z0-9]+", "_", separated).lower().split("_") if part]
    compact = "".join(parts)
    return (
        any(part in _SENSITIVE_QUERY_WORDS for part in parts)
        or compact in _SENSITIVE_QUERY_NAMES
        or compact.endswith(_SENSITIVE_QUERY_SUFFIXES)
    )


def _safe_request_url(url: str) -> str:
    """Keep the complete URL shape without writing credentials to logs."""
    safe_url = _safe_text(url)
    parts = urlsplit(safe_url)
    if not parts.query:
        return safe_url

    query = urlencode(
        [
            (key, "<redacted>" if _is_sensitive_query_key(key) else value)
            for key, value in parse_qsl(parts.query, keep_blank_values=True)
        ],
        safe="<>",
    )
    return urlunsplit((parts.scheme, parts.netloc, parts.path, query, parts.fragment))


def _client_address(request: Any) -> str:
    client = getattr(request, "client", None)
    if client is None:
        return "unknown"

    if isinstance(client, (tuple, list)):
        host = _safe_text(client[0])
        port = client[1] if len(client) > 1 else None
    else:
        host = _safe_text(getattr(client, "host", "unknown"))
        port = getattr(client, "port", None)
    if ":" in host and not host.startswith("["):
        host = f"[{host}]"
    return f"{host}:{port}" if port is not None else host


def _status_text(status_code: int) -> str:
    try:
        return HTTPStatus(status_code).phrase
    except ValueError:
        return "Unknown"


def _request_detail(request: Any, status_code: int, duration_ms: float) -> str:
    method = _safe_text(request.method).upper()
    url = _safe_request_url(str(request.url))
    http_version = _safe_text(request.scope.get("http_version") or "1.1")
    status = f"{status_code} {_status_text(status_code)}"
    return (
        f'{_client_address(request)} - "{method} {url} HTTP/{http_version}" '
        f"{status} · {duration_ms:.0f}ms"
    )


def _should_skip_success_log(path: str) -> bool:
    return path == "/favicon.ico" or path.startswith(_QUIET_PATH_PREFIXES)


async def log_http_request(request: Any, call_next: CallNext) -> Any:
    start = perf_counter()
    try:
        response = await call_next(request)
    except Exception as exc:
        detail = _request_detail(request, 500, (perf_counter() - start) * 1000)
        _log("ERROR", f"请求异常：{_safe_text(exc.__class__.__name__)}", detail)
        raise

    if response.status_code >= 400:
        detail = _request_detail(request, response.status_code, (perf_counter() - start) * 1000)
        _log("ERROR", "请求失败", detail)
    elif not _should_skip_success_log(request.url.path):
        detail = _request_detail(request, response.status_code, (perf_counter() - start) * 1000)
        level = "INFO" if request.method.upper() in _SAFE_METHODS else "SUCCESS"
        _log(level, "", detail)
    return response
