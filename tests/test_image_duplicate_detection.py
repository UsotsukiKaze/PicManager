from pathlib import Path
from contextlib import contextmanager

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from PIL import Image, ImageDraw
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app import models
from app.routers.public_api import uploads
from app.services import ImageService


def _pattern(path: Path, image_format: str) -> None:
    image = Image.new("RGB", (180, 120), "white")
    draw = ImageDraw.Draw(image)
    draw.rectangle((10, 10, 75, 105), fill="black")
    draw.ellipse((95, 20, 165, 90), fill="gray")
    image.save(path, image_format)


def test_dhash_is_stable_across_lossless_encodings(tmp_path):
    png = tmp_path / "sample.png"
    webp = tmp_path / "sample.webp"
    _pattern(png, "PNG")
    _pattern(webp, "WEBP")

    left = ImageService.compute_dhash(str(png))
    right = ImageService.compute_dhash(str(webp))

    assert len(left) == 16
    assert ImageService.dhash_distance(left, right) <= 1


def test_duplicate_search_is_scoped_to_selected_characters(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'duplicates.db'}")
    models.Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    existing_file = tmp_path / "existing.png"
    upload_file = tmp_path / "upload.webp"
    _pattern(existing_file, "PNG")
    _pattern(upload_file, "WEBP")

    with Session() as db:
        group = models.Group(name="group")
        selected = models.Character(name="selected", group=group)
        other = models.Character(name="other", group=group)
        image = models.Image(
            image_id="ABCDEF1234",
            original_filename="existing.png",
            file_extension="png",
            file_path=str(existing_file),
            file_status=ImageService.AVAILABLE,
            thumb_status=ImageService.THUMB_PENDING,
            perceptual_hash=ImageService.compute_dhash(str(existing_file)),
            characters=[selected],
        )
        db.add_all([group, selected, other, image])
        db.commit()

        _, selected_matches = ImageService.find_perceptual_duplicates(
            db, str(upload_file), [selected.id], threshold=1
        )
        _, other_matches = ImageService.find_perceptual_duplicates(
            db, str(upload_file), [other.id], threshold=1
        )

    assert [match["image_id"] for match in selected_matches] == ["ABCDEF1234"]
    assert other_matches == []


def test_duplicate_decision_token_rejects_tampering():
    token = uploads._encode_duplicate_token({"expires_at": 4_102_444_800, "match_ids": ["ABCDEF1234"]})
    assert uploads._decode_duplicate_token(token)["match_ids"] == ["ABCDEF1234"]

    encoded, signature = token.rsplit(".", 1)
    tampered = ("A" if encoded[0] != "A" else "B") + encoded[1:] + "." + signature
    with pytest.raises(HTTPException) as error:
        uploads._decode_duplicate_token(tampered)
    assert error.value.status_code == 400


def test_expired_duplicate_staging_cleanup_is_prefix_scoped(tmp_path, monkeypatch):
    monkeypatch.setattr(uploads.settings, "PENDING_PATH", str(tmp_path))
    monkeypatch.setattr(uploads.settings, "DUPLICATE_DECISION_TTL_SECONDS", 60)
    old_duplicate = tmp_path / "duplicate-old.png"
    unrelated = tmp_path / "pending-review.png"
    old_duplicate.write_bytes(b"old")
    unrelated.write_bytes(b"keep")
    old_time = 1
    import os
    os.utime(old_duplicate, (old_time, old_time))
    os.utime(unrelated, (old_time, old_time))

    uploads._cleanup_expired_duplicate_staging()

    assert not old_duplicate.exists()
    assert unrelated.exists()


def test_admin_upload_can_keep_existing_then_replace_it(tmp_path, monkeypatch):
    temp_path = tmp_path / "temp"
    pending_path = tmp_path / "pending"
    store_path = tmp_path / "store"
    thumb_path = tmp_path / "thumbs"
    for path in (temp_path, pending_path, store_path, thumb_path):
        path.mkdir()
    monkeypatch.setattr(uploads.settings, "TEMP_PATH", str(temp_path))
    monkeypatch.setattr(uploads.settings, "PENDING_PATH", str(pending_path))
    monkeypatch.setattr(uploads.settings, "STORE_PATH", str(store_path))
    monkeypatch.setattr(ImageService, "thumb_path", staticmethod(lambda image: str(thumb_path / f"{image.image_id}.webp")))

    engine = create_engine(f"sqlite:///{tmp_path / 'route.db'}", connect_args={"check_same_thread": False})
    models.Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    existing_file = store_path / "existing.png"
    upload_file = tmp_path / "upload.png"
    _pattern(existing_file, "PNG")
    _pattern(upload_file, "PNG")

    with Session() as db:
        admin = models.User(qq_number="12345", role=models.UserRole.ADMIN.value)
        group = models.Group(name="group")
        character = models.Character(name="character", group=group)
        existing = models.Image(
            image_id="ABCDEF1234",
            original_filename="existing.png",
            file_extension="png",
            file_path=str(existing_file),
            file_status=ImageService.AVAILABLE,
            thumb_status=ImageService.THUMB_PENDING,
            perceptual_hash=ImageService.compute_dhash(str(existing_file)),
            characters=[character],
        )
        db.add_all([admin, group, character, existing])
        db.commit()
        admin_id = admin.id
        character_id = character.id
        group_id = group.id

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
    monkeypatch.setattr(
        uploads,
        "get_current_session",
        lambda request, db: {"is_guest": False, "user_id": admin_id},
    )
    app = FastAPI()
    app.include_router(uploads.router)
    client = TestClient(app)
    client.cookies.set("session_id", "duplicate-route-test")

    def submit_duplicate():
        return client.post(
            "/upload/single",
            files={"file": ("upload.png", upload_file.read_bytes(), "image/png")},
            data={
                "character_ids": f"[{character_id}]",
                "group_ids": f"[{group_id}]",
                "feature_tag_ids": "[]",
                "age_rating": "all",
            },
        )

    first = submit_duplicate()
    assert first.status_code == 200
    assert first.json()["status"] == "duplicate"
    assert [item["image_id"] for item in first.json()["duplicates"]] == ["ABCDEF1234"]
    keep_existing = client.post(
        "/upload/duplicates/resolve",
        json={"token": first.json()["duplicate_token"], "keep": "existing:ABCDEF1234"},
    )
    assert keep_existing.status_code == 200
    assert keep_existing.json()["status"] == "kept_existing"
    assert list(pending_path.glob("duplicate-*")) == []

    second = submit_duplicate()
    assert second.json()["status"] == "duplicate"
    keep_new = client.post(
        "/upload/duplicates/resolve",
        json={"token": second.json()["duplicate_token"], "keep": "new"},
    )
    assert keep_new.status_code == 200
    assert keep_new.json()["status"] == "replaced_duplicates"

    with Session() as db:
        old = db.query(models.Image).filter(models.Image.image_id == "ABCDEF1234").one()
        replacement = db.query(models.Image).filter(
            models.Image.image_id == keep_new.json()["image_id"]
        ).one()
        assert old.file_status == ImageService.ARCHIVED
        assert replacement.file_status == ImageService.AVAILABLE
        stored_replacement = store_path / f"{replacement.image_id}.{replacement.file_extension}"
        assert replacement.perceptual_hash == ImageService.compute_dhash(str(stored_replacement))
