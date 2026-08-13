from io import BytesIO
import asyncio
from contextlib import contextmanager
import threading
import time

from PIL import Image
from starlette.datastructures import UploadFile
from starlette.requests import Request

from app.config import settings
from app.routers.public_api import avatars
from app.routers.public_api.avatars import process_avatar_bytes


def test_avatar_processing_outputs_square_webp_under_256_kib():
    source = Image.effect_noise((1800, 1200), 96).convert("RGB")
    raw = BytesIO()
    source.save(raw, format="PNG")

    processed = process_avatar_bytes(raw.getvalue())

    assert len(processed) <= settings.AVATAR_MAX_FILE_SIZE
    with Image.open(BytesIO(processed)) as avatar:
        assert avatar.format == "WEBP"
        assert avatar.width == avatar.height
        assert avatar.width <= settings.AVATAR_SIZE


def test_avatar_processing_noisy_rgba_is_bounded_and_fast():
    channels = [Image.effect_noise((1024, 1024), 100) for _ in range(4)]
    source = Image.merge("RGBA", channels)
    raw = BytesIO()
    source.save(raw, format="PNG", compress_level=1)

    started = time.perf_counter()
    processed = process_avatar_bytes(raw.getvalue())

    assert time.perf_counter() - started < 5
    assert len(processed) <= settings.AVATAR_MAX_FILE_SIZE
    with Image.open(BytesIO(processed)) as avatar:
        assert avatar.format == "WEBP"
        assert avatar.width == avatar.height
        assert avatar.width <= settings.AVATAR_SIZE


def test_avatar_route_offloads_processing_and_storage(monkeypatch, tmp_path):
    source = Image.new("RGB", (64, 64), "navy")
    raw = BytesIO()
    source.save(raw, format="PNG")
    processed = BytesIO()
    source.save(processed, format="WEBP")
    worker_threads = []

    def fake_process(_raw):
        worker_threads.append(threading.get_ident())
        return processed.getvalue()

    @contextmanager
    def fake_db_context():
        yield object()

    monkeypatch.setattr(avatars, "process_avatar_bytes", fake_process)
    monkeypatch.setattr(avatars, "get_db_context", fake_db_context)
    monkeypatch.setattr(avatars, "get_current_session", lambda request, db: {"session_id": "test"})
    monkeypatch.setattr(settings, "AVATAR_PATH", str(tmp_path))

    request = Request({"type": "http", "headers": []})
    upload = UploadFile(filename="avatar.png", file=BytesIO(raw.getvalue()))
    event_loop_thread = threading.get_ident()
    result = asyncio.run(avatars.process_avatar(request, upload))

    assert worker_threads and worker_threads[0] != event_loop_thread
    assert result["avatar_url"].endswith(".webp")
    assert len(list(tmp_path.glob("*.webp"))) == 1
