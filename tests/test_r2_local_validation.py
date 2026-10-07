from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

import pytest
from PIL import Image
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app import local_check, models, services
from app.config import settings
from app.services import ImageService


@pytest.mark.parametrize("mode", ["success", "changed", "download_error", "invalid", "head_error"])
def test_r2_full_validation_reuses_one_download_and_preserves_remote_records(tmp_path, monkeypatch, mode):
    monkeypatch.setattr(settings, "THUMB_PATH", str(tmp_path / "thumbs"))
    monkeypatch.setattr(settings, "PREVIEW_PATH", str(tmp_path / "previews"))
    engine = create_engine(f"sqlite:///{tmp_path / 'remote.db'}")
    models.Base.metadata.create_all(engine)
    source = tmp_path / "remote-object.png"
    Image.new("RGB", (40, 30), "red").save(source)
    downloads = []

    def exists(key):
        if mode == "head_error":
            raise TimeoutError("synthetic head error")
        return True

    def download(key, target):
        downloads.append(Path(target))
        Path(target).write_bytes(b"invalid" if mode == "invalid" else source.read_bytes())
        if mode == "download_error":
            raise TimeoutError("synthetic partial download")

    monkeypatch.setattr(services, "get_image_storage", lambda *args, **kwargs: SimpleNamespace(
        exists=exists, download_file=download))
    with Session(engine) as db:
        image = models.Image(image_id="1234567890", file_extension="png", file_path="r2://bucket/images/source.png",
                             perceptual_hash="ffffffffffffffff" if mode == "changed" else None,
                             pixiv_checked_at=datetime(2026, 1, 1))
        image.pixiv_metadata = models.PixivImageMetadata(work_id="100", page_index=0, page_count=1,
                                                        tags=[], status="verified")
        db.add(image)
        db.commit()
        result = local_check.run_batch(db, after_id="0")
        db.commit()
        assert image.file_status == "available"
        assert len(downloads) == (0 if mode == "head_error" else 1)
        assert all(not path.exists() for path in downloads)
        assert image.local_checked_at is None  # Duplicate review owns this marker.
        if mode in {"success", "changed"}:
            assert result["ready"] == 1 and not result["failed"]
            assert (image.width, image.height, image.file_size) == (40, 30, source.stat().st_size)
            assert image.perceptual_hash == ImageService.compute_dhash(str(source))
            with Image.open(ImageService.thumb_path(image)) as thumb:
                assert thumb.size == (40, 30)
            if mode == "changed":
                assert image.pixiv_metadata is None and image.pixiv_checked_at is None
        else:
            assert result["ready"] == 0 and result["failed"] == [image.image_id]
            assert image.pixiv_metadata is not None
    engine.dispose()


def test_incremental_validation_never_commits_after_database_failure(tmp_path, monkeypatch):
    from sqlalchemy.exc import SQLAlchemyError
    from app.tag_mappings import CachedImageTagCheck
    monkeypatch.setattr(settings, "THUMB_PATH", str(tmp_path / "thumbs"))
    engine = create_engine(f"sqlite:///{tmp_path / 'db-error.db'}")
    models.Base.metadata.create_all(engine)
    source = tmp_path / "source.png"
    Image.new("RGB", (20, 15), "red").save(source)
    with Session(engine) as db:
        db.add(models.Image(image_id="1234567890", file_extension="png", file_path=str(source)))
        db.commit()

        def database_failure(self, image):
            raise SQLAlchemyError("synthetic database failure")

        monkeypatch.setattr(CachedImageTagCheck, "check", database_failure)
        commits = []
        monkeypatch.setattr(db, "commit", lambda: commits.append(True))
        with pytest.raises(SQLAlchemyError, match="synthetic database failure"):
            local_check.run_batch(db, after_id="0", incremental=True)
        assert not commits
        db.rollback()
    engine.dispose()
