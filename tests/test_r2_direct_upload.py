from contextlib import contextmanager
from pathlib import Path

from PIL import Image
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app import models, schemas, services
from app.config import settings
from app.routers.public_api import uploads
from app.storage.base import StoredObject


class MemoryR2:
    def __init__(self):
        self.objects = {}

    def presigned_upload_url(self, key, *, content_type, expires=900):
        return f"https://upload.example/{key}?expires={expires}"

    def exists(self, key):
        return key in self.objects

    def download_file(self, key, target):
        Path(target).write_bytes(self.objects[key])

    def delete(self, key):
        self.objects.pop(key, None)

    def move_object(self, source_key, target_key):
        data = self.objects.pop(source_key)
        self.objects[target_key] = data
        return StoredObject(target_key, f"r2://pictures/images/{target_key}", len(data))

    def signed_download_url(self, key, *, expires=300, download_name=None):
        return f"https://download.example/{key}?expires={expires}"


def _png_bytes(tmp_path):
    path = tmp_path / "direct.png"
    Image.new("RGB", (16, 10), "green").save(path)
    return path.read_bytes()


def test_admin_can_prepare_and_finalize_r2_direct_upload(monkeypatch, tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'direct.db'}")
    models.Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)

    @contextmanager
    def database_context():
        db = Session()
        try:
            yield db
            db.commit()
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

    resource = tmp_path / "resource"
    backend = MemoryR2()
    request = type("Request", (), {"cookies": {"session_id": "admin-session"}})()
    monkeypatch.setattr(settings, "STORAGE_BACKEND", "r2")
    monkeypatch.setattr(settings, "BASE_DIR", str(tmp_path))
    monkeypatch.setattr(settings, "STORE_PATH", str(resource / "store"))
    monkeypatch.setattr(settings, "TEMP_PATH", str(resource / "temp"))
    monkeypatch.setattr(settings, "THUMB_PATH", str(resource / "thumbs"))
    monkeypatch.setattr(settings, "PREVIEW_PATH", str(resource / "previews"))
    monkeypatch.setattr(uploads, "require_admin_user_id", lambda _request: 1)
    monkeypatch.setattr(uploads, "get_db_context", database_context)
    monkeypatch.setattr(uploads, "get_image_storage", lambda _settings: backend)
    monkeypatch.setattr(services, "get_image_storage", lambda _settings, local_root=None: backend)

    with Session() as db:
        group = models.Group(name="direct-group")
        character = models.Character(name="direct-character", group=group)
        db.add_all([group, character])
        db.commit()
        group_id = group.id
        character_id = character.id

    image_bytes = _png_bytes(tmp_path)
    prepared = uploads.prepare_direct_upload(
        schemas.DirectUploadPrepare(filename="direct.png", content_type="image/png", size=len(image_bytes)),
        request,
    )
    token_payload = uploads._decode_duplicate_token(prepared["token"])
    backend.objects[token_payload["object_key"]] = image_bytes

    result = uploads.finalize_direct_upload(
        schemas.DirectUploadFinalize(
            token=prepared["token"],
            group_ids=[group_id],
            character_ids=[character_id],
        ),
        request,
    )

    assert result.status == "success"
    with Session() as db:
        image = db.get(models.Image, result.image_id)
        assert image.file_path == f"r2://pictures/images/{image.image_id}.png"
        assert {job.job_type for job in db.query(models.ImageJob).all()} == {"thumbnail", "preview"}
    assert token_payload["object_key"] not in backend.objects
    assert f"{result.image_id}.png" in backend.objects
