from pathlib import Path
from contextlib import contextmanager
import asyncio
import json

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from PIL import Image, ImageDraw
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app import models, schemas
from app.routers.admin_api import reviews
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


def test_duplicate_search_reuses_precomputed_upload_and_candidate_hashes(monkeypatch, tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'cached-duplicates.db'}")
    models.Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    cached_hash = "0123456789abcdef"

    with Session() as db:
        group = models.Group(name="group")
        character = models.Character(name="character", group=group)
        image = models.Image(
            image_id="ABCDEF1234",
            original_filename="cached.png",
            file_extension="png",
            file_path="resource/store/missing-but-already-hashed.png",
            file_status=ImageService.AVAILABLE,
            thumb_status=ImageService.THUMB_PENDING,
            perceptual_hash=cached_hash,
            characters=[character],
        )
        db.add_all([group, character, image])
        db.commit()

        monkeypatch.setattr(
            ImageService,
            "compute_dhash",
            staticmethod(lambda _path: pytest.fail("cached hashes must not decode either file again")),
        )
        returned_hash, matches = ImageService.find_perceptual_duplicates(
            db,
            "staged-upload.png",
            [character.id],
            threshold=0,
            upload_hash=cached_hash,
        )

    assert returned_hash == cached_hash
    assert [match["image_id"] for match in matches] == ["ABCDEF1234"]


def test_merge_duplicate_metadata_can_select_and_combine_fields(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'merge-duplicates.db'}")
    models.Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)

    with Session() as db:
        first_group = models.Group(name="first group")
        second_group = models.Group(name="second group")
        shared = models.Character(name="shared", group=first_group)
        extra = models.Character(name="extra", group=second_group)
        first_tag = models.FeatureTag(name="first tag")
        second_tag = models.FeatureTag(name="second tag")
        kept = models.Image(
            image_id="1111111111",
            pid="PID-A",
            description="keep description",
            age_rating="r12",
            file_extension="png",
            file_path="kept.png",
            file_status=ImageService.AVAILABLE,
            groups=[first_group],
            characters=[shared],
            feature_tags=[first_tag],
        )
        other = models.Image(
            image_id="2222222222",
            pid="PID-B",
            description="other description",
            age_rating="r18",
            file_extension="webp",
            file_path="other.webp",
            file_status=ImageService.AVAILABLE,
            groups=[second_group],
            characters=[shared, extra],
            feature_tags=[second_tag],
        )
        db.add_all([kept, other])
        db.commit()

        ImageService.merge_duplicate_image_metadata(
            db,
            kept.image_id,
            other.image_id,
            {
                "pid": "merge",
                "description": "other",
                "age_rating": "merge",
                "groups": "keep",
                "characters": "merge",
                "feature_tags": "merge",
            },
        )
        db.commit()
        db.refresh(kept)
        db.refresh(other)

        assert kept.file_path == "kept.png"
        assert kept.pid == "PID-A\nPID-B"
        assert kept.description == "other description"
        assert kept.age_rating == "r18"
        assert {group.name for group in kept.groups} == {"first group"}
        assert {character.name for character in kept.characters} == {"shared", "extra"}
        assert {tag.name for tag in kept.feature_tags} == {"first tag", "second tag"}
        assert other.file_status == ImageService.ARCHIVED


def test_merge_refuses_to_delete_when_records_share_one_physical_file(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'shared-file.db'}")
    models.Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    shared_file = tmp_path / "shared.png"
    _pattern(shared_file, "PNG")

    with Session() as db:
        group = models.Group(name="group")
        character = models.Character(name="character", group=group)
        left = models.Image(
            image_id="1111111111",
            file_extension="png",
            file_path=str(shared_file),
            file_status=ImageService.AVAILABLE,
            characters=[character],
        )
        right = models.Image(
            image_id="2222222222",
            file_extension="png",
            file_path=str(shared_file),
            file_status=ImageService.AVAILABLE,
            characters=[character],
        )
        db.add_all([left, right])
        db.commit()

        with pytest.raises(ValueError, match="same physical file"):
            ImageService.merge_duplicate_image_metadata(db, left.image_id, right.image_id)
        db.rollback()

        assert shared_file.exists()
        assert db.get(models.Image, left.image_id).file_status == ImageService.AVAILABLE
        assert db.get(models.Image, right.image_id).file_status == ImageService.AVAILABLE


def test_existing_duplicate_scan_and_resolve_are_character_scoped(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'maintenance-duplicates.db'}")
    models.Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    first_file = tmp_path / "first.png"
    second_file = tmp_path / "second.webp"
    unrelated_file = tmp_path / "unrelated.png"
    _pattern(first_file, "PNG")
    _pattern(second_file, "WEBP")
    _pattern(unrelated_file, "PNG")

    with Session() as db:
        group = models.Group(name="group")
        selected = models.Character(name="selected", group=group)
        other = models.Character(name="other", group=group)
        first = models.Image(
            image_id="1111111111",
            original_filename="first.png",
            file_extension="png",
            file_path=str(first_file),
            file_status=ImageService.AVAILABLE,
            thumb_status=ImageService.THUMB_PENDING,
            characters=[selected],
        )
        second = models.Image(
            image_id="2222222222",
            original_filename="second.webp",
            file_extension="webp",
            file_path=str(second_file),
            file_status=ImageService.AVAILABLE,
            thumb_status=ImageService.THUMB_PENDING,
            characters=[selected],
        )
        unrelated = models.Image(
            image_id="3333333333",
            original_filename="unrelated.png",
            file_extension="png",
            file_path=str(unrelated_file),
            file_status=ImageService.AVAILABLE,
            thumb_status=ImageService.THUMB_PENDING,
            characters=[other],
        )
        db.add_all([group, selected, other, first, second, unrelated])
        db.commit()

        result = ImageService.scan_existing_perceptual_duplicates(db, threshold=1)

        assert result["scanned_images"] == 3
        assert result["computed_hashes"] == 3
        assert [item["image_ids"] for item in result["groups"]] == [["1111111111", "2222222222"]]
        assert {item["image_id"] for item in result["groups"][0]["images"]} == {
            "1111111111",
            "2222222222",
        }

        excluded = ImageService.scan_existing_perceptual_duplicates(
            db,
            threshold=1,
            excluded_pairs=[["1111111111", "2222222222"]],
        )
        assert excluded["groups"] == []

        ImageService.remember_distinct_duplicate_pair(db, first.image_id, second.image_id)
        db.commit()
        durable_excluded = ImageService.scan_existing_perceptual_duplicates(db, threshold=1)
        assert durable_excluded["groups"] == []
        db.query(models.DuplicatePairDecision).delete()
        db.commit()

        archived = ImageService.resolve_existing_perceptual_duplicates(
            db,
            ["1111111111", "2222222222"],
            "2222222222",
            threshold=1,
        )
        db.commit()

        assert archived == 1
        assert first.file_status == ImageService.ARCHIVED
        assert not first_file.exists()
        assert second.file_status == ImageService.AVAILABLE
        assert second_file.exists()
        assert unrelated.file_status == ImageService.AVAILABLE


def test_existing_duplicate_resolution_rejects_images_without_shared_character(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'maintenance-safety.db'}")
    models.Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    left_file = tmp_path / "left.png"
    right_file = tmp_path / "right.png"
    _pattern(left_file, "PNG")
    _pattern(right_file, "PNG")

    with Session() as db:
        group = models.Group(name="group")
        left_character = models.Character(name="left", group=group)
        right_character = models.Character(name="right", group=group)
        left = models.Image(
            image_id="AAAAAAAAAA",
            file_extension="png",
            file_path=str(left_file),
            file_status=ImageService.AVAILABLE,
            characters=[left_character],
        )
        right = models.Image(
            image_id="BBBBBBBBBB",
            file_extension="png",
            file_path=str(right_file),
            file_status=ImageService.AVAILABLE,
            characters=[right_character],
        )
        db.add_all([group, left_character, right_character, left, right])
        db.commit()

        with pytest.raises(ValueError, match="share a character"):
            ImageService.resolve_existing_perceptual_duplicates(
                db,
                [left.image_id, right.image_id],
                left.image_id,
                threshold=0,
            )

        assert left.file_status == ImageService.AVAILABLE
        assert right.file_status == ImageService.AVAILABLE


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

    engine = create_engine(f"sqlite:///{tmp_path / 'route.db'}", connect_args={"check_same_thread": False})
    models.Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    existing_file = store_path / "existing.png"
    upload_file = tmp_path / "upload.png"
    _pattern(existing_file, "PNG")
    _pattern(upload_file, "PNG")

    with Session() as db:
        admin = models.User(qq_number="12345", role=models.UserRole.ADMIN.value)
        user = models.User(qq_number="67890", role=models.UserRole.USER.value)
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
        db.add_all([admin, user, group, character, existing])
        db.commit()
        admin_id = admin.id
        user_id = user.id
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
    current_identity = {"user_id": admin_id}
    monkeypatch.setattr(
        uploads,
        "get_current_session",
        lambda request, db: {"is_guest": False, "user_id": current_identity["user_id"]},
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
        json={
            "token": first.json()["duplicate_token"],
            "keep": "merge-existing:ABCDEF1234",
            "metadata_sources": {"pid": "merge", "characters": "merge"},
        },
    )
    assert keep_existing.status_code == 200
    assert keep_existing.json()["status"] == "merged_existing"
    assert list(pending_path.glob("duplicate-*")) == []

    second = submit_duplicate()
    assert second.json()["status"] == "duplicate"
    discarded_thumb = thumb_path / "ABCDEF1234.webp"
    discarded_thumb.write_bytes(b"thumbnail")
    keep_new = client.post(
        "/upload/duplicates/resolve",
        json={"token": second.json()["duplicate_token"], "keep": "merge-new"},
    )
    assert keep_new.status_code == 200
    assert keep_new.json()["status"] == "merged_new"

    with Session() as db:
        old = db.query(models.Image).filter(models.Image.image_id == "ABCDEF1234").one()
        replacement = db.query(models.Image).filter(
            models.Image.image_id == keep_new.json()["image_id"]
        ).one()
        assert old.file_status == ImageService.ARCHIVED
        assert not existing_file.exists()
        assert not discarded_thumb.exists()
        assert replacement.file_status == ImageService.AVAILABLE
        replacement_id = replacement.image_id
        stored_replacement = store_path / f"{replacement.image_id}.{replacement.file_extension}"
        assert replacement.perceptual_hash == ImageService.compute_dhash(str(stored_replacement))

    third = submit_duplicate()
    assert third.json()["status"] == "duplicate"
    keep_all = client.post(
        "/upload/duplicates/resolve",
        json={"token": third.json()["duplicate_token"], "keep": "distinct"},
    )
    assert keep_all.status_code == 200
    assert keep_all.json()["status"] == "kept_distinct"

    with Session() as db:
        available = db.query(models.Image).filter(
            models.Image.file_status == ImageService.AVAILABLE,
        ).all()
        assert {image.image_id for image in available} == {
            replacement_id,
            keep_all.json()["image_id"],
        }
        decision = db.query(models.DuplicatePairDecision).one()
        assert decision.pair_key == ImageService.duplicate_pair_key(replacement_id, keep_all.json()["image_id"])

    current_identity["user_id"] = user_id
    fourth = submit_duplicate()
    offered_id = fourth.json()["duplicates"][0]["image_id"]
    pending_merge = client.post(
        "/upload/duplicates/resolve",
        json={
            "token": fourth.json()["duplicate_token"],
            "keep": f"merge-existing:{offered_id}",
            "metadata_sources": {"pid": "merge", "feature_tags": "merge"},
        },
    )
    assert pending_merge.status_code == 200
    assert pending_merge.json()["status"] == "pending_review"
    with Session() as db:
        request_data = db.query(models.PendingRequest).filter(
            models.PendingRequest.user_id == user_id,
            models.PendingRequest.status == models.RequestStatus.PENDING.value,
        ).one()
        stored = json.loads(request_data.image_data)
        request_id = request_data.id
        assert stored["duplicate_keep"] == "merge-existing"
        assert stored["duplicate_image_ids"] == [offered_id]
        assert stored["duplicate_metadata_sources"]["feature_tags"] == "merge"

    monkeypatch.setattr(reviews, "get_db_context", database_context)
    monkeypatch.setattr(reviews, "require_admin_user_id", lambda _request: admin_id)
    monkeypatch.setattr(reviews.settings, "STORE_PATH", str(store_path))
    asyncio.run(reviews.handle_pending_request(
        request_id,
        schemas.PendingRequestAction(action="approve"),
        object(),
    ))
    with Session() as db:
        reviewed = db.query(models.PendingRequest).filter(models.PendingRequest.id == request_id).one()
        assert reviewed.status == models.RequestStatus.APPROVED.value
        assert reviewed.image_id == offered_id
        assert db.query(models.Image).count() == 3
