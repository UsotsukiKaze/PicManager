from contextlib import contextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient
from PIL import Image, ImageDraw
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app import models
from app.routers.public_api import uploads
from app.services import ImageService


def _pattern(path: Path) -> None:
    image = Image.new("RGB", (180, 120), "white")
    draw = ImageDraw.Draw(image)
    draw.rectangle((10, 10, 75, 105), fill="black")
    draw.ellipse((95, 20, 165, 90), fill="gray")
    image.save(path, "PNG")


def test_temp_scan_can_merge_with_archived_or_stored_image(tmp_path, monkeypatch):
    temp_path = tmp_path / "temp"
    store_path = tmp_path / "store"
    thumb_path = tmp_path / "thumbs"
    pending_path = tmp_path / "pending"
    for path in (temp_path, store_path, thumb_path, pending_path):
        path.mkdir()
    monkeypatch.setattr(uploads.settings, "TEMP_PATH", str(temp_path))
    monkeypatch.setattr(uploads.settings, "STORE_PATH", str(store_path))
    monkeypatch.setattr(uploads.settings, "THUMB_PATH", str(thumb_path))
    monkeypatch.setattr(uploads.settings, "PENDING_PATH", str(pending_path))
    monkeypatch.setattr(ImageService, "thumb_path", staticmethod(lambda image: str(thumb_path / f"{image.image_id}.webp")))
    monkeypatch.setattr(
        ImageService,
        "image_full_path",
        staticmethod(
            lambda image: (
                image.file_path
                if Path(image.file_path).is_absolute()
                else str(store_path / f"{image.image_id}.{image.file_extension}")
            )
        ),
    )

    engine = create_engine(f"sqlite:///{tmp_path / 'temp-duplicates.db'}", connect_args={"check_same_thread": False})
    models.Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    stored_file = store_path / "archived.png"
    first_temp = temp_path / "114514.png"
    _pattern(stored_file)
    _pattern(first_temp)

    with Session() as db:
        admin = models.User(qq_number="12345", role=models.UserRole.ADMIN.value)
        group = models.Group(name="group")
        character = models.Character(name="character", group=group)
        tag = models.FeatureTag(name="tag")
        stored = models.Image(
            image_id="ABCDEF1234",
            pid="old-pid",
            description="old description",
            age_rating="r12",
            original_filename="archived.png",
            file_extension="png",
            file_path=str(stored_file),
            file_status=ImageService.ARCHIVED,
            thumb_status=ImageService.THUMB_PENDING,
            perceptual_hash=ImageService.compute_dhash(str(stored_file)),
            groups=[group],
            characters=[character],
            feature_tags=[tag],
        )
        db.add_all([admin, stored])
        db.commit()
        admin_id = admin.id
        group_id = group.id
        character_id = character.id
        tag_id = tag.id

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

    monkeypatch.setattr(uploads, "get_db_context", database_context)
    monkeypatch.setattr(uploads, "require_admin_user_id", lambda _request: admin_id)
    app = FastAPI()
    app.include_router(uploads.router)
    client = TestClient(app)
    client.cookies.set("session_id", "temp-duplicate-test")

    scan = client.post("/upload/temp-duplicates/scan?limit=1")
    assert scan.status_code == 200
    match = scan.json()["matches"][0]
    assert match["filename"] == "114514.png"
    assert match["filename_stem"] == "114514"
    assert match["temp"]["character_ids"] == []
    assert match["stored"]["image_id"] == "ABCDEF1234"
    assert match["stored"]["file_status"] == "archived"
    assert match["stored"]["feature_tag_names"] == ["tag"]

    keep_existing = client.post(
        "/upload/temp-duplicates/resolve",
        json={
            "token": match["duplicate_token"],
            "keep": "existing",
            "metadata": {
                "group_ids": [group_id],
                "character_ids": [character_id],
                "feature_tag_ids": [tag_id],
                "pid": "114514",
                "description": "edited",
                "age_rating": "r16",
            },
        },
    )
    assert keep_existing.status_code == 200
    assert keep_existing.json()["status"] == "merged_existing"
    assert not first_temp.exists()
    assert stored_file.exists()
    with Session() as db:
        stored = db.get(models.Image, "ABCDEF1234")
        assert stored.file_status == ImageService.AVAILABLE
        assert stored.pid == "114514"
        assert stored.description == "edited"
        assert stored.age_rating == "r16"

    second_temp = temp_path / "keep-temp.png"
    _pattern(second_temp)
    second_scan = client.post("/upload/temp-duplicates/scan?limit=1").json()["matches"][0]
    keep_temp = client.post(
        "/upload/temp-duplicates/resolve",
        json={
            "token": second_scan["duplicate_token"],
            "keep": "temp",
            "metadata": {
                "group_ids": [group_id],
                "character_ids": [character_id],
                "feature_tag_ids": [tag_id],
                "pid": "new-pid",
                "description": "keep temp",
                "age_rating": "all",
            },
        },
    )
    assert keep_temp.status_code == 200
    assert keep_temp.json()["status"] == "merged_new"
    assert not second_temp.exists()
    assert not stored_file.exists()
    with Session() as db:
        old = db.get(models.Image, "ABCDEF1234")
        replacement = db.get(models.Image, keep_temp.json()["image_id"])
        assert old.file_status == ImageService.ARCHIVED
        assert replacement.file_status == ImageService.AVAILABLE
        assert replacement.pid == "new-pid"
        assert ImageService.image_file_exists(replacement)
