from contextlib import contextmanager

import pytest
from fastapi import Request, Response
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

import main
from app import models, schemas
from app.models import UserRole
from app.routers.auth_api import sessions
from app.routers.integrations import bot as bot_routes
from app.security.lan_debug import configured_lan_base_url, configured_lan_hosts
from app.security.session_cookies import set_auth_cookie


def _request(*, host: str, scheme: str = "http") -> Request:
    return Request({
        "type": "http",
        "http_version": "1.1",
        "method": "POST",
        "scheme": scheme,
        "path": "/auth/guest",
        "raw_path": b"/auth/guest",
        "query_string": b"",
        "headers": [(b"host", host.encode("ascii"))],
        "server": (host, 8777 if scheme == "http" else 443),
        "client": ("192.168.18.20", 12345),
    })


def _database_context(monkeypatch, *modules):
    engine = create_engine("sqlite:///:memory:")
    models.Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine)

    @contextmanager
    def database_context():
        db = session_factory()
        try:
            yield db
            db.commit()
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

    for module in modules:
        monkeypatch.setattr(module, "get_db_context", database_context)
    return session_factory


def test_lan_debug_off_does_not_add_ip_host(monkeypatch):
    monkeypatch.setattr(main.settings, "TRUSTED_HOSTS", "localhost,pic.usotsuki-kaze.com")
    monkeypatch.setattr(main.settings, "LAN_DEBUG_ENABLED", False)
    monkeypatch.setattr(main.settings, "LAN_DEBUG_HOSTS", "192.168.18.14")

    assert "192.168.18.14" not in main._trusted_hosts()

    from fastapi import FastAPI
    from starlette.middleware.trustedhost import TrustedHostMiddleware

    app = FastAPI()
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=main._trusted_hosts())

    @app.get("/health")
    def health():
        return {"ok": True}

    assert TestClient(app).get("/health", headers={"Host": "192.168.18.14:8777"}).status_code == 400


def test_lan_debug_adds_only_exact_configured_host(monkeypatch):
    monkeypatch.setattr(main.settings, "TRUSTED_HOSTS", "localhost,pic.usotsuki-kaze.com")
    monkeypatch.setattr(main.settings, "LAN_DEBUG_ENABLED", True)
    monkeypatch.setattr(main.settings, "LAN_DEBUG_HOSTS", "192.168.18.14")
    monkeypatch.setattr(main.settings, "LAN_DEBUG_BASE_URL", "http://192.168.18.14:8777")

    assert main._trusted_hosts() == ["localhost", "pic.usotsuki-kaze.com", "192.168.18.14"]
    assert configured_lan_hosts(main.settings) == ["192.168.18.14"]
    assert configured_lan_base_url(main.settings) == "http://192.168.18.14:8777"


def test_lan_debug_rejects_wildcards(monkeypatch):
    monkeypatch.setattr(main.settings, "LAN_DEBUG_ENABLED", True)
    monkeypatch.setattr(main.settings, "LAN_DEBUG_HOSTS", "192.168.18.*")

    with pytest.raises(RuntimeError):
        configured_lan_hosts(main.settings)


def test_cookie_secure_policy_is_host_and_scheme_bound(monkeypatch):
    monkeypatch.setattr(sessions.settings, "SESSION_COOKIE_SECURE", True)
    monkeypatch.setattr(sessions.settings, "LAN_DEBUG_ENABLED", True)
    monkeypatch.setattr(sessions.settings, "LAN_DEBUG_HOSTS", "192.168.18.14")

    lan_response = Response()
    set_auth_cookie(lan_response, _request(host="192.168.18.14"), key="session_id", value="lan", max_age=60)
    public_response = Response()
    set_auth_cookie(
        public_response,
        _request(host="pic.usotsuki-kaze.com", scheme="https"),
        key="session_id",
        value="public",
        max_age=60,
    )
    other_lan_response = Response()
    set_auth_cookie(other_lan_response, _request(host="192.168.18.15"), key="session_id", value="other", max_age=60)

    assert "Secure" not in lan_response.headers["set-cookie"]
    assert "Secure" in public_response.headers["set-cookie"]
    assert "Secure" in other_lan_response.headers["set-cookie"]


@pytest.mark.asyncio
async def test_lan_guest_stays_guest_and_gets_http_cookie(monkeypatch):
    session_factory = _database_context(monkeypatch, sessions)
    monkeypatch.setattr(sessions.settings, "SESSION_COOKIE_SECURE", True)
    monkeypatch.setattr(sessions.settings, "LAN_DEBUG_ENABLED", True)
    monkeypatch.setattr(sessions.settings, "LAN_DEBUG_HOSTS", "192.168.18.14")

    response = Response()
    result = await sessions.guest_login(_request(host="192.168.18.14"), response)

    assert result["is_guest"] is True
    assert all("Secure" not in value for value in response.headers.getlist("set-cookie"))
    with session_factory() as db:
        saved = db.query(models.UserSession).one()
        assert saved.is_guest == "true"
        assert saved.user_id is None


@pytest.mark.asyncio
async def test_lan_root_still_requires_root_qq_ticket(monkeypatch):
    session_factory = _database_context(monkeypatch, sessions, bot_routes)
    root_qq = "123456789"
    monkeypatch.setattr(sessions, "ROOT_QQ", root_qq)
    monkeypatch.setattr(bot_routes.settings, "ROOT_QQ", root_qq)
    monkeypatch.setattr(bot_routes.settings, "PUBLIC_BASE_URL", "https://pic.example")
    monkeypatch.setattr(bot_routes.settings, "LAN_DEBUG_ENABLED", True)
    monkeypatch.setattr(bot_routes.settings, "LAN_DEBUG_HOSTS", "192.168.18.14")
    monkeypatch.setattr(bot_routes.settings, "LAN_DEBUG_BASE_URL", "http://192.168.18.14:8777")
    monkeypatch.setattr(sessions, "fetch_qq_info", lambda qq: None)

    async def fake_qq_info(qq):
        return {"nickname": f"QQ{qq[-4:]}", "avatar_url": "https://avatar.example/root.png"}

    monkeypatch.setattr(sessions, "fetch_qq_info", fake_qq_info)
    ticket = bot_routes.create_bot_login_ticket(schemas.BotLoginTicketCreate(qq_number=root_qq))
    assert ticket.lan_login_url.startswith("http://192.168.18.14:8777/login?")

    response = Response()
    result = await sessions.login_with_qq_ticket(
        schemas.QQTicketLogin(ticket=ticket.ticket),
        _request(host="192.168.18.14"),
        response,
    )

    assert result["user"].role == UserRole.ROOT.value
    assert "Secure" not in response.headers["set-cookie"]
    with session_factory() as db:
        user = db.query(models.User).filter(models.User.qq_number == root_qq).one()
        assert user.role == UserRole.ROOT.value

    ordinary_qq = "987654321"
    ordinary_ticket = bot_routes.create_bot_login_ticket(schemas.BotLoginTicketCreate(qq_number=ordinary_qq))
    ordinary_result = await sessions.login_with_qq_ticket(
        schemas.QQTicketLogin(ticket=ordinary_ticket.ticket),
        _request(host="192.168.18.14"),
        Response(),
    )
    assert ordinary_result["user"].role == UserRole.USER.value


def test_trusted_host_middleware_can_be_constructed_for_lan(monkeypatch):
    monkeypatch.setattr(main.settings, "TRUSTED_HOSTS", "localhost,pic.usotsuki-kaze.com")
    monkeypatch.setattr(main.settings, "LAN_DEBUG_ENABLED", True)
    monkeypatch.setattr(main.settings, "LAN_DEBUG_HOSTS", "192.168.18.14")
    monkeypatch.setattr(main.settings, "LAN_DEBUG_BASE_URL", "http://192.168.18.14:8777")

    # Middleware captures its startup configuration, so use a minimal app for
    # the exact allow/reject behavior while testing the same host builder.
    from fastapi import FastAPI
    from starlette.middleware.trustedhost import TrustedHostMiddleware

    app = FastAPI()
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=main._trusted_hosts())

    @app.get("/health")
    def health():
        return {"ok": True}

    client = TestClient(app)
    assert client.get("/health", headers={"Host": "192.168.18.14:8777"}).status_code == 200
    assert client.get("/health", headers={"Host": "192.168.18.15:8777"}).status_code == 400
