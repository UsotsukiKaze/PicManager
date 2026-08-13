from contextlib import contextmanager
import inspect
import threading

from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from app.routers.public_api import emojis, uploads
from app.routers.integrations import bot


def test_upload_route_runs_blocking_image_work_off_event_loop(monkeypatch, tmp_path):
    threads = {}

    class FakeDb:
        pass

    @contextmanager
    def fake_db_context():
        yield FakeDb()

    def stop_at_pillow_verification(path):
        threads["image_work"] = threading.get_ident()
        raise HTTPException(status_code=418, detail="verification reached")

    monkeypatch.setattr(uploads.settings, "TEMP_PATH", str(tmp_path))
    monkeypatch.setattr(uploads, "get_db_context", fake_db_context)
    monkeypatch.setattr(uploads, "get_current_session", lambda request, db: {
        "is_guest": True,
        "guest_ip": "127.0.0.1",
        "guest_name": "guest",
    })
    monkeypatch.setattr(uploads, "check_guest_limit", lambda db, ip: True)
    monkeypatch.setattr(uploads, "_verify_image_file", stop_at_pillow_verification)

    app = FastAPI()

    @app.middleware("http")
    async def record_event_loop_thread(request, call_next):
        threads["event_loop"] = threading.get_ident()
        return await call_next(request)

    app.include_router(uploads.router)
    response = TestClient(app).post(
        "/upload/single",
        files={"file": ("image.png", b"payload", "image/png")},
        data={"character_ids": "[]"},
    )

    assert response.status_code == 418
    assert not inspect.iscoroutinefunction(uploads.upload_single_image)
    assert threads["image_work"] != threads["event_loop"]


def test_emoji_upload_route_is_sync_for_pillow_and_file_work():
    assert not inspect.iscoroutinefunction(emojis.upload_emoji)


def test_bot_emoji_upload_is_also_offloaded_as_sync_route():
    assert not inspect.iscoroutinefunction(bot.upload_bot_emoji)
