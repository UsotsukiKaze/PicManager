from contextlib import contextmanager
from datetime import datetime, timedelta
from io import BytesIO

import pytest
from fastapi import FastAPI, HTTPException, Request, Response, UploadFile
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app import models, schemas
from app.config import Settings
from app.routers.auth_api import sessions
from app.routers.public_api import emojis, groups, images, uploads


def _request(*, cookie=None, client="127.0.0.1"):
    headers = []
    if cookie:
        headers.append((b"cookie", cookie.encode("ascii")))
    return Request({
        "type": "http",
        "method": "POST",
        "path": "/",
        "headers": headers,
        "client": (client, 12345),
        "scheme": "http",
        "server": ("testserver", 80),
        "query_string": b"",
    })


def _database_context(monkeypatch, module):
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

    monkeypatch.setattr(module, "get_db_context", database_context)
    return session_factory


def test_debug_defaults_to_false_without_env_file():
    assert Settings(_env_file=None, _env_prefix="PICMANAGER_TEST_NO_ENV_").DEBUG is False


@pytest.mark.parametrize('method,path', [('POST', '/auth/login'), ('PUT', '/auth/password')])
@pytest.mark.parametrize('body', [None, b'{"qq_number":"test","password":"synthetic","old_password":"synthetic","new_password":"synthetic"}', b'not-json'])
def test_removed_password_flows_always_reject_without_processing_credentials(monkeypatch, method, path, body):
    monkeypatch.setattr(sessions, 'get_db_context', lambda: pytest.fail('Disabled password endpoint accessed database'))
    app = FastAPI()
    app.include_router(sessions.router, prefix='/auth')
    response = TestClient(app).request(method, path, content=body, headers={'Content-Type': 'application/json'})
    assert response.status_code == 410
    assert 'set-cookie' not in response.headers
    assert 'synthetic' not in response.text
    assert 'requestBody' not in app.openapi()['paths'][path][method.lower()]


@pytest.mark.asyncio
async def test_debug_loopback_guest_login_never_becomes_root(monkeypatch):
    session_factory = _database_context(monkeypatch, sessions)
    monkeypatch.setattr(sessions.settings, "DEBUG", True)
    monkeypatch.setattr(sessions.settings, "DEBUG_GUEST_ROOT", False)

    result = await sessions.guest_login(_request(), Response())

    assert result["is_guest"] is True
    assert "debug_login" not in result
    with session_factory() as db:
        saved = db.query(models.UserSession).one()
        assert saved.is_guest == "true"
        assert saved.user_id is None
        assert db.query(models.User).count() == 0


@pytest.mark.asyncio
async def test_explicit_local_debug_guest_login_becomes_root(monkeypatch):
    session_factory = _database_context(monkeypatch, sessions)
    monkeypatch.setattr(sessions.settings, "DEBUG", True)
    monkeypatch.setattr(sessions.settings, "DEBUG_GUEST_ROOT", True)
    monkeypatch.setattr(sessions.settings, "SESSION_COOKIE_SECURE", True)
    monkeypatch.setattr(sessions.settings, "SESSION_COOKIE_DOMAIN", "pic.usotsuki-kaze.com")
    request = _request()
    request.scope["server"] = ("localhost", 8778)
    response = Response()
    result = await sessions.guest_login(request, response)
    assert result["is_guest"] is False
    assert result["user"].role == "root"
    cookie = response.headers["set-cookie"]
    assert "Domain=" not in cookie and "Secure" not in cookie
    assert "HttpOnly" in cookie
    with session_factory() as db:
        saved = db.query(models.UserSession).one()
        assert saved.is_guest == "false" and saved.user_id is not None


@pytest.mark.parametrize("debug,client,host,headers", [
    (False, "127.0.0.1", "localhost", []),
    (True, "192.168.1.2", "localhost", []),
    (True, "127.0.0.1", "pic.usotsuki-kaze.com", []),
    (True, "127.0.0.1", "localhost", [(b"x-forwarded-for", b"192.168.1.2")]),
])
def test_debug_root_login_requires_direct_loopback(monkeypatch, debug, client, host, headers):
    monkeypatch.setattr(sessions.settings, "DEBUG", debug)
    monkeypatch.setattr(sessions.settings, "DEBUG_GUEST_ROOT", True)
    request = _request(client=client)
    request.scope["server"] = (host, 8778)
    request.scope["headers"] = headers
    assert sessions.local_debug_root_login(request) is False


def test_ordinary_write_without_session_returns_401(monkeypatch):
    _database_context(monkeypatch, images)

    with pytest.raises(HTTPException) as exc_info:
        images.update_image("missing", schemas.ImageUpdate(description="edit"), _request())

    assert exc_info.value.status_code == 401

    with pytest.raises(HTTPException) as exc_info:
        images.delete_image("missing", _request())

    assert exc_info.value.status_code == 401


def test_upload_without_session_returns_401(monkeypatch):
    _database_context(monkeypatch, uploads)
    file = UploadFile(filename="image.png", file=BytesIO(b"not-read-before-auth"))

    with pytest.raises(HTTPException) as exc_info:
        uploads.upload_single_image(
            request=_request(),
            file=file,
            character_ids="[]",
            group_id=None,
            group_ids=None,
            feature_tag_ids=None,
            emotion_ids=None,
            pid=None,
            description=None,
            age_rating="all",
        )

    assert exc_info.value.status_code == 401


def test_original_download_without_session_returns_401(monkeypatch):
    _database_context(monkeypatch, images)

    with pytest.raises(HTTPException) as exc_info:
        images.download_image("missing", _request())

    assert exc_info.value.status_code == 401


def test_emoji_download_without_session_returns_401(monkeypatch):
    _database_context(monkeypatch, emojis)

    with pytest.raises(HTTPException) as exc_info:
        emojis.download_emoji("missing", _request())

    assert exc_info.value.status_code == 401


def test_signed_guest_session_can_submit_normal_write(monkeypatch):
    session_factory = _database_context(monkeypatch, groups)
    with session_factory() as db:
        db.add(models.UserSession(
            session_id="signed-guest-session",
            user_id=None,
            guest_ip="127.0.0.1",
            guest_name="guest",
            is_guest="true",
            expires_at=datetime.utcnow() + timedelta(days=1),
        ))
        db.commit()

    result = groups.create_group(
        schemas.GroupCreate(name="guest-created-group"),
        _request(cookie="session_id=signed-guest-session"),
    )

    assert isinstance(result, dict)
    with session_factory() as db:
        pending = db.query(models.PendingRequest).one()
        assert pending.request_type == "group_add"
        assert pending.guest_name == "guest"
