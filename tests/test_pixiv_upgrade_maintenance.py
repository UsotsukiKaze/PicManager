from pathlib import Path
from datetime import datetime

import pytest
from PIL import Image as PILImage
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app import models
from app.config import settings
from app.pixiv import PixivCandidate, PixivClient, PixivLookupError, PixivUpgradeService
from app.schemas import ImageUpdate
from app.services import ImageService


@pytest.fixture(autouse=True)
def _reset_shared_pixiv_client():
    PixivUpgradeService.close_client()
    PixivUpgradeService._LAST_SCAN_STARTED_AT = 0.0
    yield
    PixivUpgradeService.close_client()


def _database():
    engine = create_engine("sqlite:///:memory:")
    models.Base.metadata.create_all(engine)
    return sessionmaker(bind=engine)()


def _image(tmp_path: Path, image_id: str, pid: str | None, color: str = "red") -> models.Image:
    path = tmp_path / f"{image_id}.png"
    PILImage.new("RGB", (32, 24), color).save(path)
    return models.Image(
        image_id=image_id,
        pid=pid,
        original_filename=path.name,
        file_extension="png",
        file_size=path.stat().st_size,
        width=32,
        height=24,
        file_path=str(path),
        file_status="available",
    )


def test_pixiv_client_uses_configured_http_proxy_without_logging_it(monkeypatch):
    captured = {}

    class FakeTransport:
        def __init__(self, *, proxy, limits):
            captured["proxy"] = proxy
            captured["limits"] = limits

    class FakeClient:
        def __init__(self, **options):
            captured["options"] = options

        def close(self):
            pass

    monkeypatch.setattr(settings, "PIXIV_PROXY", "http://proxy-user:proxy-pass@127.0.0.1:7890")
    monkeypatch.setattr("app.pixiv.httpx.HTTPTransport", FakeTransport)
    monkeypatch.setattr("app.pixiv.httpx.Client", FakeClient)

    client = PixivClient()
    client.close()

    assert captured["proxy"] == "http://proxy-user:proxy-pass@127.0.0.1:7890"
    assert "transport" in captured["options"]
    assert captured["limits"].max_connections == 4
    assert captured["limits"].max_keepalive_connections == 2


def test_scan_reuses_bounded_client_and_throttles_between_images(tmp_path, monkeypatch):
    db = _database()
    db.add_all([
        _image(tmp_path, "1111111111", "123456"),
        _image(tmp_path, "2222222222", "234567"),
    ])
    db.commit()
    created = []
    closed = []
    sleeps = []

    class FakeClient:
        def __init__(self):
            created.append(self)

        def close(self):
            closed.append(self)

    clock = iter((10.0, 10.0, 10.1, 10.5))
    monkeypatch.setattr(settings, "PIXIV_SCAN_INTERVAL_SECONDS", 0.5)
    monkeypatch.setattr("app.pixiv.PixivClient", FakeClient)
    monkeypatch.setattr("app.pixiv.time.monotonic", lambda: next(clock))
    monkeypatch.setattr("app.pixiv.time.sleep", lambda seconds: sleeps.append(seconds))
    monkeypatch.setattr(PixivUpgradeService, "cleanup_staged", lambda: None)
    monkeypatch.setattr(PixivUpgradeService, "find_candidate", lambda image, client: None)

    PixivUpgradeService.scan_next(db)
    PixivUpgradeService.scan_next(db)

    assert len(created) == 1
    assert closed == []
    assert sleeps == [pytest.approx(0.4)]
    PixivUpgradeService.close_client()
    assert closed == created


def test_pixiv_proxy_rejects_unsupported_or_malformed_urls(monkeypatch):
    for proxy in ("socks5://127.0.0.1:7890", "http://127.0.0.1:not-a-port"):
        monkeypatch.setattr(settings, "PIXIV_PROXY", proxy)
        try:
            PixivClient()
        except PixivLookupError as exc:
            assert proxy not in str(exc)
        else:
            raise AssertionError("invalid Pixiv proxy must be rejected")


def test_only_ascii_numeric_pids_are_selected_and_ignored_rows_stay_unmarked(tmp_path):
    db = _database()
    ignored_x = _image(tmp_path, "1111111111", "X:123456")
    ignored_empty = _image(tmp_path, "2222222222", None)
    ignored_unicode = _image(tmp_path, "3333333333", "１２３")
    eligible = _image(tmp_path, "4444444444", "123456")
    db.add_all([ignored_x, ignored_empty, ignored_unicode, eligible])
    db.commit()

    assert PixivUpgradeService.next_image(db).image_id == eligible.image_id
    assert ignored_x.pixiv_checked_at is None
    assert ignored_empty.pixiv_checked_at is None
    assert ignored_unicode.pixiv_checked_at is None


def test_completed_lookup_without_upgrade_marks_only_the_numeric_pid(tmp_path, monkeypatch):
    db = _database()
    ignored = _image(tmp_path, "1111111111", "X:123456")
    eligible = _image(tmp_path, "2222222222", "123456")
    db.add_all([ignored, eligible])
    db.commit()
    monkeypatch.setattr(PixivUpgradeService, "cleanup_staged", lambda: None)
    monkeypatch.setattr(PixivUpgradeService, "find_candidate", lambda image, client=None: None)

    result = PixivUpgradeService.scan_next(db)

    assert result["status"] == "checked"
    assert result["remaining"] == 0
    assert eligible.pixiv_checked_at is not None
    assert ignored.pixiv_checked_at is None


def test_matching_higher_resolution_pixiv_page_is_staged(tmp_path, monkeypatch):
    pending = tmp_path / "pending"
    pending.mkdir()
    monkeypatch.setattr(settings, "PENDING_PATH", str(pending))
    current = _image(tmp_path, "1111111111", "123456")
    with PILImage.open(current.file_path) as source:
        higher = source.resize((64, 48), PILImage.Resampling.NEAREST)

    class FakeClient:
        def pages(self, pid):
            assert pid == "123456"
            return [{
                "width": 64,
                "height": 48,
                "urls": {
                    "regular": "https://i.pximg.net/sample/123456_p0.jpg",
                    "original": "https://i.pximg.net/original/123456_p0.jpg",
                },
            }]

        def download(self, url, destination):
            higher.save(destination, "JPEG")
            return 64, 48, destination.stat().st_size

    candidate = PixivUpgradeService.find_candidate(current, FakeClient())

    assert candidate is not None
    assert (candidate.width, candidate.height) == (64, 48)
    assert candidate.page_index == 0
    assert candidate.staged_path.is_file()
    candidate.staged_path.unlink()


def test_skip_removes_staged_candidate_and_marks_image_checked(tmp_path, monkeypatch):
    pending = tmp_path / "pending"
    pending.mkdir()
    monkeypatch.setattr(settings, "PENDING_PATH", str(pending))
    db = _database()
    image = _image(tmp_path, "1111111111", "123456")
    db.add(image)
    db.commit()
    filename = "pixiv-upgrade-0123456789abcdef0123456789abcdef.png"
    staged = pending / filename
    PILImage.new("RGB", (64, 48), "blue").save(staged)
    candidate = PixivCandidate(
        staged_path=staged,
        filename=filename,
        width=64,
        height=48,
        file_size=staged.stat().st_size,
        page_index=0,
        source_url="https://i.pximg.net/img-original/example.png",
        distance=0,
    )
    token = PixivUpgradeService.make_token(image, candidate)

    result = PixivUpgradeService.resolve(db, token, "skip")

    assert result["status"] == "skipped"
    assert image.pixiv_checked_at is not None
    assert not staged.exists()


def test_changing_pid_clears_the_checked_marker(tmp_path):
    db = _database()
    image = _image(tmp_path, "1111111111", "123456")
    image.pixiv_checked_at = datetime.utcnow()
    db.add(image)
    db.commit()

    ImageService.update_image(db, image.image_id, ImageUpdate(pid="654321"))

    assert image.pid == "654321"
    assert image.pixiv_checked_at is None


def test_confirmed_candidate_replaces_original_and_refreshes_metadata(tmp_path, monkeypatch):
    base = tmp_path / "base"
    store = base / "resource" / "store"
    pending = base / "resource" / "pending"
    thumbs = base / "resource" / "thumbs"
    store.mkdir(parents=True)
    pending.mkdir(parents=True)
    monkeypatch.setattr(settings, "BASE_DIR", str(base))
    monkeypatch.setattr(settings, "STORE_PATH", str(store))
    monkeypatch.setattr(settings, "PENDING_PATH", str(pending))
    monkeypatch.setattr(settings, "THUMB_PATH", str(thumbs))
    db = _database()
    old_path = store / "1111111111.png"
    PILImage.new("RGB", (32, 24), "red").save(old_path)
    image = models.Image(
        image_id="1111111111",
        pid="123456",
        original_filename=old_path.name,
        file_extension="png",
        file_size=old_path.stat().st_size,
        width=32,
        height=24,
        file_path="resource/store/1111111111.png",
        file_status="available",
    )
    db.add(image)
    db.commit()
    filename = "pixiv-upgrade-0123456789abcdef0123456789abcdef.jpg"
    staged = pending / filename
    PILImage.new("RGB", (64, 48), "blue").save(staged, "JPEG")
    candidate = PixivCandidate(
        staged_path=staged,
        filename=filename,
        width=64,
        height=48,
        file_size=staged.stat().st_size,
        page_index=0,
        source_url="https://i.pximg.net/img-original/123456_p0.jpg",
        distance=0,
    )
    token = PixivUpgradeService.make_token(image, candidate)

    result = PixivUpgradeService.resolve(db, token, "replace")

    assert result["status"] == "replaced"
    assert (image.width, image.height) == (64, 48)
    assert image.file_extension == "jpg"
    assert image.file_path == "resource/store/1111111111.jpg"
    assert image.pixiv_checked_at is not None
    assert not old_path.exists()
    assert (store / "1111111111.jpg").is_file()
    assert (thumbs / "1111111111.webp").is_file()


def test_frontend_exposes_review_before_pixiv_replace():
    root = Path(__file__).resolve().parents[1]
    html = (root / "static/index.html").read_text(encoding="utf-8")
    api_source = (root / "static/js/api.js").read_text(encoding="utf-8")
    ui_source = (root / "static/js/ui.js").read_text(encoding="utf-8")
    auth_source = (root / "static/js/auth.js").read_text(encoding="utf-8")

    assert 'id="scan-pixiv-upgrades-button"' in html
    assert 'id="pixiv-upgrade-progress-bar"' in html
    assert "/system/pixiv-upgrades/next" in api_source
    assert "/system/pixiv-upgrades/resolve" in api_source
    assert "await reviewPixivUpgrade(result)" in ui_source
    assert "updatePixivUpgradeProgress" in ui_source
    assert "result.remaining" in ui_source
    assert 'data-pixiv-action="replace"' in ui_source
    assert 'data-pixiv-auto-review' in ui_source
    assert "let seconds = 10" in ui_source
    assert "finish('replace')" in ui_source
    assert "pixivAutoReviewEnabled" in ui_source
    assert "await api.resolvePixivUpgrade(result.token, action)" in ui_source
    assert '/static/js/auth.js?v=20260820e' in html
    assert '/static/js/api.js?v=20260820b' in auth_source
    assert '/static/js/ui.js?v=20260820d' in auth_source
    assert '/static/css/style.css?v=20260820e' in auth_source
