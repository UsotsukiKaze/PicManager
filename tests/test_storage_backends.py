import errno
from pathlib import Path

from PIL import Image

from app.config import settings
from app.services import ImageService
from app.storage import LocalStorage, R2Storage


def test_local_storage_uses_atomic_move_and_returns_database_locator(tmp_path):
    source = tmp_path / "staged.jpg"
    source.write_bytes(b"image-bytes")
    backend = LocalStorage(tmp_path / "resource" / "store", base_dir=tmp_path)

    stored = backend.put_file(source, "ABCDEF1234.jpg", move=True)

    assert not source.exists()
    assert stored.locator == "resource/store/ABCDEF1234.jpg"
    assert backend.local_path(stored.key).read_bytes() == b"image-bytes"


def test_local_storage_falls_back_to_copy_then_delete_across_filesystems(monkeypatch, tmp_path):
    source = tmp_path / "staged.jpg"
    source.write_bytes(b"cross-device")
    backend = LocalStorage(tmp_path / "store", base_dir=tmp_path)

    def cross_device(*args):
        raise OSError(errno.EXDEV, "cross-device link")

    monkeypatch.setattr("app.storage.local.os.replace", cross_device)
    stored = backend.put_file(source, "nested/ABCDEF1234.jpg", move=True)

    assert not source.exists()
    assert backend.local_path(stored.key).read_bytes() == b"cross-device"


class FakeR2Client:
    def __init__(self):
        self.uploads = []
        self.deleted = []

    def upload_file(self, source, bucket, key):
        self.uploads.append((Path(source).read_bytes(), bucket, key))

    def head_object(self, **kwargs):
        return {"ContentLength": 1}

    def delete_object(self, **kwargs):
        self.deleted.append(kwargs)

    def copy_object(self, **kwargs):
        self.copied = kwargs

    def generate_presigned_url(self, operation, Params, ExpiresIn):
        return f"https://r2.example/{Params['Key']}?expires={ExpiresIn}"


def test_r2_backend_keeps_object_keys_opaque_and_removes_source_only_after_upload(tmp_path):
    source = tmp_path / "staged.jpg"
    source.write_bytes(b"r2-image")
    client = FakeR2Client()
    backend = R2Storage(
        account_id="account",
        bucket="pictures",
        access_key_id="key",
        secret_access_key="secret",
        prefix="images",
        client=client,
    )

    stored = backend.put_file(source, "ABCDEF1234.jpg", move=True)

    assert not source.exists()
    assert stored.locator == "r2://pictures/images/ABCDEF1234.jpg"
    assert client.uploads == [(b"r2-image", "pictures", "images/ABCDEF1234.jpg")]
    assert backend.signed_download_url(stored.key, expires=60).endswith("expires=60")

    upload_url = backend.presigned_upload_url("incoming/new.jpg", content_type="image/jpeg", expires=90)
    assert upload_url.endswith("expires=90")
    moved = backend.move_object(stored.key, "published.jpg")
    assert moved.locator == "r2://pictures/images/published.jpg"
    assert client.copied["CopySource"]["Key"] == "images/ABCDEF1234.jpg"


def test_image_service_moves_local_staged_file_instead_of_copying(monkeypatch, tmp_path):
    source = tmp_path / "staged.png"
    Image.new("RGB", (8, 6), "red").save(source)
    store = tmp_path / "resource" / "store"
    monkeypatch.setattr(settings, "BASE_DIR", str(tmp_path))
    monkeypatch.setattr(settings, "STORAGE_BACKEND", "local")

    locator, info = ImageService.save_image_file(
        str(source), "ABCDEF1234", "png", str(store)
    )

    assert not source.exists()
    assert locator == "resource/store/ABCDEF1234.png"
    assert info["file_size"] > 0
