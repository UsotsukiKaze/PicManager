from __future__ import annotations

from contextlib import contextmanager
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from starlette.requests import Request

from app.models import UserRole
from app.routers.integrations import kaze_apps


def request_from(host: str) -> Request:
    return Request({"type": "http", "method": "POST", "path": "/", "headers": [], "client": (host, 1234)})


def test_internal_auth_rejects_non_loopback(monkeypatch) -> None:
    monkeypatch.setattr(kaze_apps.settings, "KAZE_APPS_INTERNAL_TOKEN", "shared-token")
    with pytest.raises(HTTPException) as error:
        kaze_apps._require_internal_request(request_from("192.0.2.10"), "Bearer shared-token")
    assert error.value.status_code == 403


def test_internal_auth_rejects_wrong_token(monkeypatch) -> None:
    monkeypatch.setattr(kaze_apps.settings, "KAZE_APPS_INTERNAL_TOKEN", "shared-token")
    with pytest.raises(HTTPException) as error:
        kaze_apps._require_internal_request(request_from("127.0.0.1"), "Bearer wrong-token")
    assert error.value.status_code == 403


def test_root_session_is_validated_over_loopback(monkeypatch) -> None:
    monkeypatch.setattr(kaze_apps.settings, "KAZE_APPS_INTERNAL_TOKEN", "shared-token")
    monkeypatch.setattr(kaze_apps.settings, "ROOT_QQ", "1356890337")
    monkeypatch.setattr(
        kaze_apps,
        "get_session",
        lambda _db, _session_id: {"is_guest": False, "user_id": 42},
    )

    class Query:
        def filter(self, *_args):
            return self

        def first(self):
            return SimpleNamespace(
                id=42,
                role=UserRole.ROOT.value,
                qq_number="1356890337",
                nickname="拈风",
            )

    class Database:
        def query(self, _model):
            return Query()

    @contextmanager
    def fake_database():
        yield Database()

    monkeypatch.setattr(kaze_apps, "get_db_context", fake_database)
    result = kaze_apps.verify_root_session(
        kaze_apps.RootSessionCheck(session_id="x" * 20),
        request_from("127.0.0.1"),
        "Bearer shared-token",
    )
    assert result == {"authenticated": True, "isRoot": True, "nickname": "拈风"}
