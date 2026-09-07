from types import SimpleNamespace

import pytest
from starlette.requests import Request

from app import logger


def _request(method: str, target: str, *, http_version: str = "1.1") -> Request:
    path, separator, query = target.partition("?")
    return Request(
        {
            "type": "http",
            "asgi": {"version": "3.0"},
            "http_version": http_version,
            "method": method,
            "scheme": "https",
            "path": path,
            "raw_path": path.encode(),
            "query_string": query.encode() if separator else b"",
            "headers": [(b"host", b"pic.example")],
            "client": ("127.0.0.1", 43120),
            "server": ("pic.example", 443),
        }
    )


def test_default_output_highlights_level_only_and_mutes_detail(capsys):
    logger._default_log_hook("SUCCESS", "请求完成", "POST https://pic.example/api/upload HTTP/1.1 → 200")

    assert capsys.readouterr().out == (
        "\033[92mSUCCESS: \033[0m请求完成  "
        "\033[90mPOST https://pic.example/api/upload HTTP/1.1 → 200\033[0m\n"
    )


def test_plain_log_uses_standard_aligned_prefix_without_coloring_message(capsys):
    logger._default_log_hook("INFO", "服务已启动")
    logger._default_log_hook("ERROR", "启动失败")

    assert capsys.readouterr().out == (
        "\033[94mINFO:    \033[0m服务已启动\n"
        "\033[91mERROR:   \033[0m启动失败\n"
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("method", "expected_level"),
    [("GET", "INFO"), ("HEAD", "INFO"), ("POST", "SUCCESS"), ("DELETE", "SUCCESS")],
)
async def test_successful_request_level_and_complete_context(monkeypatch, method, expected_level):
    events = []
    times = iter((10.0, 10.012))
    monkeypatch.setattr(logger, "_log_hook", lambda level, message: events.append((level, message)))
    monkeypatch.setattr(logger, "perf_counter", lambda: next(times))

    async def call_next(_request):
        return SimpleNamespace(status_code=200)

    response = await logger.log_http_request(
        _request(method, "/api/images/search?name=cat&ticket=top-secret", http_version="2"),
        call_next,
    )

    assert response.status_code == 200
    assert events == [
        (
            expected_level,
            '127.0.0.1:43120 - "'
            f"{method} https://pic.example/api/images/search?name=cat&ticket=<redacted> HTTP/2"
            '" 200 OK · 12ms',
        )
    ]
    assert "top-secret" not in events[0][1]


@pytest.mark.asyncio
async def test_http_error_uses_chinese_summary_and_request_context(monkeypatch):
    events = []
    times = iter((20.0, 20.004))
    monkeypatch.setattr(logger, "_log_hook", lambda level, message: events.append((level, message)))
    monkeypatch.setattr(logger, "perf_counter", lambda: next(times))

    async def call_next(_request):
        return SimpleNamespace(status_code=403)

    await logger.log_http_request(_request("DELETE", "/api/images/ABC"), call_next)

    assert events == [
        (
            "ERROR",
            '请求失败  127.0.0.1:43120 - "DELETE https://pic.example/api/images/ABC HTTP/1.1" '
            "403 Forbidden · 4ms",
        )
    ]


@pytest.mark.asyncio
async def test_unhandled_exception_logs_only_safe_type_and_is_reraised(monkeypatch):
    events = []
    times = iter((30.0, 30.006))
    monkeypatch.setattr(logger, "_log_hook", lambda level, message: events.append((level, message)))
    monkeypatch.setattr(logger, "perf_counter", lambda: next(times))

    async def call_next(_request):
        raise RuntimeError("token=top-secret")

    with pytest.raises(RuntimeError, match="top-secret"):
        await logger.log_http_request(_request("POST", "/api/groups"), call_next)

    assert events == [
        (
            "ERROR",
            '请求异常：RuntimeError  127.0.0.1:43120 - "POST https://pic.example/api/groups HTTP/1.1" '
            "500 Internal Server Error · 6ms",
        )
    ]
    assert "top-secret" not in events[0][1]


@pytest.mark.asyncio
async def test_successful_static_request_stays_quiet(monkeypatch):
    events = []
    monkeypatch.setattr(logger, "_log_hook", lambda level, message: events.append((level, message)))

    async def call_next(_request):
        return SimpleNamespace(status_code=200)

    await logger.log_http_request(_request("GET", "/static/app.js"), call_next)

    assert events == []


def test_sensitive_query_values_are_redacted():
    safe_url = logger._safe_request_url(
        "https://pic.example/login?accessToken=one&apiKey=two&sessionId=three"
        "&pwd=four&user%5Bpassword%5D=five&signature=six&monkey=banana"
    )

    assert safe_url.count("<redacted>") == 6
    assert "one" not in safe_url
    assert "two" not in safe_url
    assert "three" not in safe_url
    assert "four" not in safe_url
    assert "five" not in safe_url
    assert "six" not in safe_url
    assert "monkey=banana" in safe_url


def test_request_context_strips_terminal_controls_and_handles_missing_client():
    class UnsafeUrl:
        path = "/"

        def __str__(self):
            return "https://pic.example/\033[32m"

    request = SimpleNamespace(
        client=None,
        method="GE\033[31mT",
        url=UnsafeUrl(),
        scope={"http_version": "1.1\033[1m"},
    )

    detail = logger._request_detail(request, 200, 3)

    assert "\033" not in detail
    assert detail.startswith("unknown -")


def test_ipv6_client_address_is_unambiguous():
    request = _request("GET", "/health")
    request.scope["client"] = ("2001:db8::1", 43120)

    assert logger._client_address(request) == "[2001:db8::1]:43120"


def test_request_logger_is_outermost_user_middleware():
    import main

    middleware = main.app.user_middleware[0]
    assert middleware.kwargs.get("dispatch") is main.log_requests
