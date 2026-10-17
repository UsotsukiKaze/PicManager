from contextlib import contextmanager
from pathlib import Path
from tempfile import NamedTemporaryFile
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from PIL import Image as PillowImage
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app import models, visual_similarity
from app.routers.integrations import bot, bot_search
from app.services import ImageService


def run_immediate(coroutine):
    """The fake upload completes without an event loop or network."""
    try:
        coroutine.send(None)
    except StopIteration as completed:
        return completed.value
    raise AssertionError("Unexpected asynchronous operation")


class FakeUpload:
    async def read(self, _size):
        return b"quoted image"


@contextmanager
def fake_database():
    yield SimpleNamespace()


def test_pid_search_prefers_exact_library_page(monkeypatch):
    calls = []
    monkeypatch.setattr(bot_search, "get_db_context", fake_database)
    monkeypatch.setattr(bot_search, "library_pixiv_image", lambda db, work, page: calls.append((work, page)) or SimpleNamespace(image_id="local"))
    monkeypatch.setattr(bot_search, "_local_result", lambda db, image_id, audience, audience_id: {"source": "library", "image_id": image_id})
    monkeypatch.setattr(bot_search, "_remote_result", lambda *args: pytest.fail("Pixiv must not be called for a library hit"))

    result = bot_search.pid_search("123456_p2", audience="group", audience_id="42")

    assert calls == [("123456", 2)]
    assert result == {"source": "library", "image_id": "local"}


def test_pid_search_does_not_fallback_after_library_permission_denied(monkeypatch):
    monkeypatch.setattr(bot_search, "get_db_context", fake_database)
    monkeypatch.setattr(bot_search, "library_pixiv_image", lambda *args: SimpleNamespace(image_id="restricted"))

    def denied(*args):
        raise HTTPException(403, "restricted")

    monkeypatch.setattr(bot_search, "_local_result", denied)
    monkeypatch.setattr(bot_search, "_remote_result", lambda *args: pytest.fail("Pixiv must not bypass library permissions"))

    with pytest.raises(HTTPException) as error:
        bot_search.pid_search("123456", audience="group", audience_id="42")
    assert error.value.status_code == 403


def test_library_result_recovers_pid_from_pixiv_metadata(monkeypatch):
    class Lookup:
        def __init__(self, model):
            self.model = model

        def filter_by(self, **kwargs):
            assert kwargs == {"image_id": "local"}
            return self

        def first(self):
            if self.model is models.PixivImageMetadata:
                return SimpleNamespace(work_id="123456", page_index=2)
            pytest.fail("Pixiv source fallback should not run")

    db = SimpleNamespace(query=lambda model: Lookup(model))
    monkeypatch.setattr(ImageService, "get_image", lambda db, image_id: {
        "image_id": image_id, "pid": None, "age_rating": "all"
    })
    monkeypatch.setattr(bot_search, "_permitted", lambda *args: True)
    monkeypatch.setattr(bot, "_with_image_url", lambda image: image)

    result = bot_search._local_result(db, "local", "group", "42")

    assert result["pid"] == "123456_p2"


def test_artist_ambiguity_returns_uids_without_drawing(monkeypatch):
    monkeypatch.setattr(bot_search, "get_db_context", fake_database)
    monkeypatch.setattr(bot_search, "_local_artists", lambda db, name: [
        SimpleNamespace(id="1", name="artist"), SimpleNamespace(id="2", name="artist")
    ])
    monkeypatch.setattr(bot_search, "_artist_image", lambda *args: pytest.fail("Ambiguous artist must not draw"))

    result = bot_search.artist_search(name="artist", audience="group", audience_id="42")

    assert result == {"candidates": [{"id": "1", "name": "artist"}, {"id": "2", "name": "artist"}]}


def test_artist_exact_catalog_check_does_not_contact_pixiv(monkeypatch):
    monkeypatch.setattr(bot_search, "get_db_context", fake_database)
    monkeypatch.setattr(bot_search, "_local_artists", lambda db, name: [SimpleNamespace(id="9", name="Artist")])
    monkeypatch.setattr(bot_search, "_remote_artist", lambda *args: pytest.fail("Catalog check must stay local"))

    result = bot_search.artist_search(name="artist", audience="group", audience_id="42", local_only=True)

    assert result == {"candidates": [{"id": "9", "name": "Artist"}]}


def test_artist_search_prefers_library_image(monkeypatch):
    monkeypatch.setattr(bot_search, "get_db_context", fake_database)
    monkeypatch.setattr(bot_search, "_local_artists", lambda db, name: [SimpleNamespace(id="9", name="Artist")])
    monkeypatch.setattr(bot_search, "_artist_image", lambda *args: {"source": "library", "pid": "123_p0"})
    monkeypatch.setattr(bot_search, "_remote_artist", lambda *args: pytest.fail("Pixiv must not be called for a library hit"))

    result = bot_search.artist_search(name="Artist", audience="group", audience_id="42")

    assert result == {"source": "library", "pid": "123_p0"}


def test_remote_artist_search_uses_resolved_artist_and_filters_artwork(monkeypatch):
    class FakeClient:
        def __init__(self):
            self.calls = []

        def call(self, method, **kwargs):
            self.calls.append((method, kwargs))
            if method == "search_user":
                return {"user_previews": [{"user": {"id": 9, "name": "artist"}}]}
            return {"illusts": [{"id": 123}]}

        def close(self):
            pass

    client = FakeClient()
    monkeypatch.setattr(bot_search, "get_db_context", fake_database)
    monkeypatch.setattr(bot_search, "_pixiv_account", lambda db: SimpleNamespace(owner_id=7, revision="revision", preferences={}))
    monkeypatch.setattr(bot_search.pixiv_service, "client_for_job", lambda actor, revision: client)
    monkeypatch.setattr(bot_search.pixiv_service, "normalize_artwork", lambda raw: {
        "pid": "123", "author_id": "9", "x_restrict": 0
    })
    monkeypatch.setattr(bot_search, "_permitted", lambda *args: True)
    monkeypatch.setattr(bot_search, "_save_remote", lambda *args: None)
    monkeypatch.setattr(bot_search, "_remote_result", lambda *args: {"source": "pixiv", "pid": "123_p0"})

    result = bot_search._remote_artist("artist", None, "group", "42")

    assert result["pid"] == "123_p0"
    assert client.calls == [
        ("search_user", {"word": "artist"}),
        ("user_illusts", {"user_id": 9, "type": "illust"}),
    ]


class EmptyQuery:
    def outerjoin(self, *args):
        return self

    def filter(self, *args):
        return self

    def first(self):
        return None


@contextmanager
def empty_index_database():
    yield SimpleNamespace(query=lambda *args: EmptyQuery())


def test_quoted_image_requires_reliable_match(monkeypatch):
    monkeypatch.setattr(bot_search, "get_db_context", empty_index_database)
    monkeypatch.setattr(bot_search, "match_cached_preview", lambda *args, **kwargs: [
        {"image_id": "first", "score": 98.2}, {"image_id": "second", "score": 97.5}
    ])
    monkeypatch.setattr(bot_search, "_local_result", lambda *args: pytest.fail("Ambiguous match must not send an image"))
    image = FakeUpload()

    with pytest.raises(HTTPException) as error:
        run_immediate(bot_search.image_match(image=image, audience="group", audience_id="42"))
    assert error.value.status_code == 404


def test_quoted_image_returns_matching_library_image(monkeypatch):
    monkeypatch.setattr(bot_search, "get_db_context", empty_index_database)
    monkeypatch.setattr(bot_search, "match_cached_preview", lambda *args, **kwargs: [
        {"image_id": "first", "score": 99.0}
    ])
    monkeypatch.setattr(bot_search, "_local_result", lambda db, image_id, audience, audience_id: {
        "source": "library", "image_id": image_id, "pid": "123456_p0"
    })
    image = FakeUpload()

    result = run_immediate(bot_search.image_match(image=image, audience="group", audience_id="42"))
    assert result["image_id"] == "first"
    assert result["pid"] == "123456_p0"


def test_full_library_fingerprint_matches_image_with_pid(monkeypatch):
    engine = create_engine("sqlite:///:memory:")
    models.Base.metadata.create_all(engine)
    with NamedTemporaryFile(suffix=".png", delete=False) as temporary:
        path = Path(temporary.name)
    try:
        image = PillowImage.new("RGB", (96, 96))
        image.putdata([((x * 3) % 256, (y * 5) % 256, (x + y) % 256)
                       for y in range(96) for x in range(96)])
        image.save(path)
        monkeypatch.setattr(ImageService, "image_full_path", lambda image: str(path))
        visual_similarity.INDEX.clear()
        with Session(engine) as db:
            db.add(models.Image(image_id="ABCDEF1234", pid="123456_p0", file_path="managed.png",
                                file_extension="png", file_status="available", thumb_status="pending"))
            db.commit()
            assert visual_similarity.index_missing_batch(db, include_identified=True)["processed"] == 1
            db.commit()
            matches = visual_similarity.match_cached_preview(db, path, include_identified=True)
        assert matches[0] == {"image_id": "ABCDEF1234", "score": 100.0}
    finally:
        visual_similarity.INDEX.clear()
        path.unlink(missing_ok=True)
        engine.dispose()
