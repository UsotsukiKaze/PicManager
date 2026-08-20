from fastapi import Request, Response
from fastapi.testclient import TestClient
import pytest

import main


def _request(path: str, method: str = "GET") -> Request:
    return Request(
        {
            "type": "http",
            "http_version": "1.1",
            "method": method,
            "scheme": "https",
            "path": path.split("?", 1)[0],
            "raw_path": path.split("?", 1)[0].encode(),
            "query_string": path.partition("?")[2].encode(),
            "headers": [],
            "server": ("pic.example", 443),
            "client": ("127.0.0.1", 12345),
        }
    )


async def _ok_response(_request: Request) -> Response:
    return Response("ok", media_type="text/html")


@pytest.mark.asyncio
async def test_production_app_shell_is_shared_only_at_cloudflare(monkeypatch):
    monkeypatch.setattr(main.settings, "DEBUG", False)

    response = await main.prevent_stale_ui_cache(_request("/"), _ok_response)

    assert response.headers["cache-control"] == "no-cache"
    assert response.headers["cloudflare-cdn-cache-control"] == (
        "public, max-age=60, stale-while-revalidate=30, stale-if-error=86400"
    )
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["x-frame-options"] == "DENY"
    assert "default-src 'self'" in response.headers["content-security-policy"]
    assert "object-src 'none'" in response.headers["content-security-policy"]


@pytest.mark.asyncio
async def test_versioned_static_assets_are_immutable(monkeypatch):
    monkeypatch.setattr(main.settings, "DEBUG", False)

    response = await main.prevent_stale_ui_cache(
        _request("/static/js/main.js?v=release-1"),
        _ok_response,
    )

    assert response.headers["cache-control"] == "public, max-age=31536000, immutable"
    assert response.headers["cloudflare-cdn-cache-control"] == response.headers["cache-control"]


@pytest.mark.asyncio
async def test_login_and_profile_are_never_cached(monkeypatch):
    monkeypatch.setattr(main.settings, "DEBUG", False)

    for path in ("/login", "/profile"):
        response = await main.prevent_stale_ui_cache(_request(path), _ok_response)
        assert response.headers["cache-control"].startswith("no-store")
        assert response.headers["cloudflare-cdn-cache-control"] == "no-store"


@pytest.mark.asyncio
async def test_debug_ui_assets_are_never_cached(monkeypatch):
    monkeypatch.setattr(main.settings, "DEBUG", True)

    response = await main.prevent_stale_ui_cache(
        _request("/static/js/main.js?v=release-1"),
        _ok_response,
    )

    assert response.headers["cache-control"].startswith("no-store")
    assert response.headers["cloudflare-cdn-cache-control"] == "no-store"


def test_public_hosts_are_explicitly_allowlisted():
    assert "*" not in main._trusted_hosts()
    assert "pic.usotsuki-kaze.com" in main._trusted_hosts()
    assert "localhost" in main._trusted_hosts()


def test_trusted_host_middleware_rejects_unknown_hosts():
    client = TestClient(main.app)

    rejected = client.get("/health", headers={"Host": "attacker.example"})
    accepted = client.get("/health", headers={"Host": "pic.usotsuki-kaze.com"})

    assert rejected.status_code == 400
    assert accepted.status_code == 200
