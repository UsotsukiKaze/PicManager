from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace

import pytest

import main
from app.services import ImageService


@pytest.mark.asyncio
async def test_thumbnail_route_never_falls_back_to_original(monkeypatch, tmp_path):
    thumb_root = tmp_path / "thumbs"
    store_root = tmp_path / "store"
    thumb_root.mkdir()
    store_root.mkdir()
    original = store_root / "ABCDEF1234.jpg"
    original.write_bytes(b"large-original")

    monkeypatch.setattr(main.settings, "THUMB_PATH", str(thumb_root))
    monkeypatch.setattr(main.settings, "STORE_PATH", str(store_root))

    response = await main.thumbnail_file("ABCDEF1234.webp")

    assert Path(response.path).name == "placeholder.png"
    assert Path(response.path) != original
    assert response.headers["cache-control"] == "public, max-age=60"
    assert response.headers["x-picmanager-thumbnail"] == "missing"


@pytest.mark.asyncio
async def test_thumbnail_route_serves_cached_webp(monkeypatch, tmp_path):
    thumb_root = tmp_path / "thumbs"
    thumb_root.mkdir()
    thumbnail = thumb_root / "ABCDEF1234.webp"
    thumbnail.write_bytes(b"small-webp")
    monkeypatch.setattr(main.settings, "THUMB_PATH", str(thumb_root))

    response = await main.thumbnail_file("ABCDEF1234.webp")

    assert Path(response.path) == thumbnail
    assert response.media_type == "image/webp"
    assert response.headers["cache-control"] == "public, max-age=604800, immutable"


def test_original_route_resolves_published_image_by_id(monkeypatch, tmp_path):
    store_root = tmp_path / "store"
    store_root.mkdir()
    original = store_root / "ABCDEF1234.jpg"
    original.write_bytes(b"large-original")
    image = SimpleNamespace(
        image_id="ABCDEF1234",
        file_path="resource/store/ABCDEF1234.jpg",
        file_status=ImageService.AVAILABLE,
    )

    class FakeQuery:
        def filter(self, *args):
            return self

        def first(self):
            return image

    class FakeDb:
        def query(self, model):
            return FakeQuery()

    @contextmanager
    def fake_db_context():
        yield FakeDb()

    monkeypatch.setattr(main.settings, "STORE_PATH", str(store_root))
    monkeypatch.setattr(main, "get_db_context", fake_db_context)

    response = main.original_image("ABCDEF1234")

    assert Path(response.path) == original
    assert response.headers["cache-control"] == "public, max-age=604800, immutable"
