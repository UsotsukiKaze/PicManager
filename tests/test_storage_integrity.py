from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

import pytest
from PIL import Image
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker
from starlette.responses import Response

import main
from app import models, schemas, services
from app.config import settings
from app.services import ImageService
from app.storage import LocalStorage, R2Storage
from app.storage.base import StoredObject


@pytest.fixture
def database(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "DATA_PATH", str(tmp_path / "data"))
    engine = create_engine(f"sqlite:///{tmp_path / 'integrity.db'}")

    @event.listens_for(engine, "connect")
    def foreign_keys(connection, record):
        connection.execute("PRAGMA foreign_keys=ON")

    models.Base.metadata.create_all(engine)
    try:
        with sessionmaker(bind=engine)() as db:
            yield db
    finally:
        engine.dispose()


class RemoteError(Exception):
    def __init__(self, code):
        self.response = {"Error": {"Code": code}}


@pytest.mark.parametrize("code,missing", [
    ("404", True), ("NoSuchKey", True), ("NotFound", True),
    ("AccessDenied", False), ("NoSuchBucket", False), ("SlowDown", False),
])
def test_remote_absence_requires_explicit_object_not_found(code, missing):
    def head(**kwargs):
        raise RemoteError(code)

    backend = R2Storage(account_id="account", bucket="bucket", access_key_id="key",
                        secret_access_key="secret", client=SimpleNamespace(head_object=head))
    if missing:
        assert backend.exists("test.png") is False
    else:
        with pytest.raises(RemoteError):
            backend.exists("test.png")


@pytest.mark.parametrize("mode", ["archive", "delete"])
def test_remote_timeout_never_archives_or_deletes_records(database, monkeypatch, tmp_path, mode):
    image = models.Image(image_id="1111111111", file_extension="png", file_path="r2://bucket/images/test.png",
                         file_status="available", local_checked_at=datetime.utcnow())
    database.add(image)
    database.commit()

    def unavailable(key):
        raise TimeoutError("synthetic timeout")

    monkeypatch.setattr(services, "get_image_storage", lambda *args, **kwargs: SimpleNamespace(exists=unavailable))
    with pytest.raises(TimeoutError):
        ImageService.cleanup_orphaned_records(database, str(tmp_path), mode=mode)
    database.rollback()
    assert database.get(models.Image, image.image_id).file_status == "available"
    assert image.local_checked_at is not None


@pytest.mark.parametrize("remote", [False, True])
def test_delete_removes_original_derivatives_and_dependent_jobs(database, monkeypatch, tmp_path, remote):
    monkeypatch.setattr(settings, "THUMB_PATH", str(tmp_path / "thumbs"))
    monkeypatch.setattr(settings, "PREVIEW_PATH", str(tmp_path / "previews"))
    source = tmp_path / "original.png"
    source.write_bytes(b"original")
    deleted = []
    monkeypatch.setattr(services, "get_image_storage", lambda *args, **kwargs: SimpleNamespace(delete=deleted.append))
    image = models.Image(image_id="1111111111", file_extension="png",
                         file_path="r2://bucket/images/test.png" if remote else str(source))
    database.add(image)
    database.flush()
    database.add_all([
        models.ImageJob(image_id=image.image_id, job_type="thumbnail"),
        models.ImageViewCount(image_id=image.image_id),
        models.DuplicatePairDecision(pair_key="1111111111:2222222222",
                                    left_image_id=image.image_id, right_image_id="2222222222"),
    ])
    database.commit()
    thumb, preview = Path(ImageService.thumb_path(image)), Path(ImageService.preview_path(image))
    thumb.write_bytes(b"thumbnail")
    preview.write_bytes(b"preview")
    assert ImageService.delete_image(database, image.image_id, str(tmp_path))
    assert database.get(models.Image, image.image_id) is None
    assert database.query(models.ImageJob).count() == 0
    assert database.query(models.ImageViewCount).count() == 0
    assert database.query(models.DuplicatePairDecision).count() == 0
    assert not thumb.exists() and not preview.exists()
    if remote:
        assert deleted == ["images/test.png"]
    else:
        assert not source.exists()


def test_remote_delete_failure_is_durable_and_retried(database, monkeypatch, tmp_path):
    from app import file_operations
    import json
    image = models.Image(image_id="1111111111", file_extension="png", file_path="r2://bucket/images/test.png")
    database.add(image)
    database.commit()
    monkeypatch.setattr(settings, "STORAGE_BACKEND", "r2")

    def unavailable(key):
        raise TimeoutError("synthetic timeout")

    monkeypatch.setattr(services, "get_image_storage", lambda *args, **kwargs: SimpleNamespace(delete=unavailable))
    assert ImageService.delete_image(database, image.image_id, str(tmp_path))
    assert database.get(models.Image, image.image_id) is None
    assert database.query(models.FileOperationReceipt).count() == 1
    intent = next((tmp_path / "data").rglob("*.json"))
    record = json.loads(intent.read_text())
    assert record["attempts"] == 1
    deleted = []
    monkeypatch.setattr(file_operations, "get_image_storage", lambda *args, **kwargs: SimpleNamespace(delete=deleted.append))
    assert file_operations.recover(database) == 0  # Backoff is observed.
    monkeypatch.setattr(file_operations.time, "time", lambda: record["retry_after"] + 1)
    assert file_operations.recover(database) == 1
    assert deleted == ["images/test.png"]
    assert not intent.exists()
    database.expire_all()
    assert database.query(models.FileOperationReceipt).count() == 0


@pytest.mark.parametrize("kind", ["thumbnail", "preview"])
def test_failed_encoding_preserves_existing_derivative(monkeypatch, tmp_path, kind):
    source, target = tmp_path / "source.png", tmp_path / "derivative.webp"
    Image.new("RGB", (20, 20), "red").save(source)
    target.write_bytes(b"previous working derivative")

    def broken_save(self, path, *args, **kwargs):
        Path(path).write_bytes(b"partial encoding")
        raise OSError("synthetic encoding failure")

    monkeypatch.setattr(Image.Image, "save", broken_save)
    with pytest.raises(OSError):
        getattr(ImageService, f"write_{kind}")(str(source), str(target))
    assert target.read_bytes() == b"previous working derivative"
    assert {path.name for path in tmp_path.iterdir()} == {"source.png", "derivative.webp"}


def test_r2_thumbnail_maintenance_downloads_source(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "THUMB_PATH", str(tmp_path / "thumbs"))
    source = tmp_path / "source.png"
    Image.new("RGB", (20, 15), "red").save(source)
    downloads = []

    def download(key, target):
        downloads.append((key, Path(target)))
        Path(target).write_bytes(source.read_bytes())

    monkeypatch.setattr(services, "get_image_storage", lambda *args, **kwargs: SimpleNamespace(
        exists=lambda key: True, download_file=download))
    image = models.Image(image_id="1111111111", file_extension="png", file_path="r2://bucket/images/source.png")
    assert ImageService.ensure_thumbnail(image, force=True)
    with Image.open(ImageService.thumb_path(image)) as thumb:
        assert thumb.size == (20, 15)
    assert downloads[0][0] == "images/source.png"
    assert not downloads[0][1].exists()


def test_csp_allows_only_configured_r2_endpoint(monkeypatch):
    monkeypatch.setattr(settings, "STORAGE_BACKEND", "r2")
    monkeypatch.setattr(settings, "R2_ACCOUNT_ID", "a" * 32)
    monkeypatch.setattr(settings, "R2_BUCKET", "pictures")
    response = Response()
    main._apply_security_headers(response)
    connect = response.headers["content-security-policy"].split("connect-src ")[1]
    assert f"https://{'a' * 32}.r2.cloudflarestorage.com" in connect
    assert "https:" not in connect.split()
    monkeypatch.setattr(settings, "R2_ACCOUNT_ID", "bad; connect-src *")
    main._apply_security_headers(response)
    assert response.headers["content-security-policy"].endswith("connect-src 'self'")


@pytest.mark.parametrize("phase", ["flush", "commit"])
@pytest.mark.parametrize("remote", [False, True])
def test_failed_image_commit_preserves_retry_source_and_cleans_target(database, monkeypatch, tmp_path, remote, phase):
    source = tmp_path / "staged.png"
    Image.new("RGB", (20, 15), "red").save(source)
    original = source.read_bytes()
    store = tmp_path / "store"
    monkeypatch.setattr(settings, "STORAGE_BACKEND", "local")
    monkeypatch.setattr(ImageService, "generate_image_id", lambda: "1111111111")
    objects = {"incoming/source.png": original}
    if remote:
        def copy(key, target):
            objects[target] = objects[key]
            return StoredObject(target, f"r2://bucket/{target}", len(objects[target]))
        backend = SimpleNamespace(copy_object=copy, delete=lambda key: objects.pop(key, None))
    else:
        backend = LocalStorage(store, base_dir=tmp_path)
    monkeypatch.setattr(services, "get_image_storage", lambda *args, **kwargs: backend)

    original_flush = database.flush

    def database_failure(*args, **kwargs):
        if phase == "flush" and not database.new:
            return original_flush(*args, **kwargs)
        assert ("1111111111.png" in objects) if remote else backend.exists("1111111111.png")
        raise RuntimeError("synthetic database failure")

    with monkeypatch.context() as failure:
        failure.setattr(database, phase, database_failure)
        with pytest.raises(RuntimeError, match="synthetic database failure"):
            ImageService.create_image(database, schemas.ImageCreate(), str(source), "staged.png", "png", str(store),
                                      storage_source_key="incoming/source.png" if remote else None)
    assert source.read_bytes() == original
    assert database.get(models.Image, "1111111111") is None
    assert database.query(models.ImageJob).count() == 0
    if remote:
        assert objects == {"incoming/source.png": original}
    else:
        assert list(store.iterdir()) == []
