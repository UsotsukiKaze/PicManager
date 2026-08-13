from fastapi import HTTPException
import pytest

from app import schemas
from app.routers import system
from app.services import SystemService


class _CountQuery:
    def __init__(self, value):
        self.value = value

    def scalar(self):
        return self.value


class _FakeDb:
    def __init__(self):
        self.values = iter((10, 20, 30, 40))

    def query(self, expression):
        return _CountQuery(next(self.values))


def test_public_status_only_contains_home_counters():
    status = SystemService.get_public_status(_FakeDb())

    assert status.model_dump() == {
        "total_images": 10,
        "total_emojis": 20,
        "total_groups": 30,
        "total_characters": 40,
    }


def test_diagnostics_requires_admin_before_database_work(monkeypatch):
    monkeypatch.setattr(
        system,
        "require_admin_user_id",
        lambda request: (_ for _ in ()).throw(HTTPException(status_code=401)),
    )

    try:
        system.get_system_diagnostics(object())
    except HTTPException as exc:
        assert exc.status_code == 401
    else:
        raise AssertionError("diagnostics must require admin")


def test_existing_duplicate_maintenance_requires_admin(monkeypatch):
    monkeypatch.setattr(
        system,
        "require_admin_user_id",
        lambda request: (_ for _ in ()).throw(HTTPException(status_code=401)),
    )

    with pytest.raises(HTTPException) as scan_error:
        system.scan_existing_duplicates(object())
    assert scan_error.value.status_code == 401

    choice = schemas.ExistingDuplicateResolveRequest(
        image_ids=["1111111111", "2222222222"],
        keep_image_id="1111111111",
    )
    with pytest.raises(HTTPException) as resolve_error:
        system.resolve_existing_duplicates(choice, object())
    assert resolve_error.value.status_code == 401
