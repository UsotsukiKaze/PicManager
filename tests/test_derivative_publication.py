from contextlib import contextmanager
from datetime import datetime, timedelta
from pathlib import Path
import os
import time

import pytest
from PIL import Image
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app import jobs, models
from app.config import settings
from app.services import ImageService


@pytest.mark.parametrize("kind", ["thumbnail", "preview"])
@pytest.mark.parametrize("change", ["none", "version", "physical", "delete", "lease", "missing", "publish_error"])
def test_publish_only_with_current_source_and_lease(tmp_path, monkeypatch, kind, change):
    engine = create_engine(f"sqlite:///{tmp_path / 'derivatives.db'}")
    models.Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine)
    monkeypatch.setattr(settings, "THUMB_PATH", str(tmp_path / "thumbs"))
    monkeypatch.setattr(settings, "PREVIEW_PATH", str(tmp_path / "previews"))
    source = tmp_path / "source.png"
    Image.new("RGB", (20, 15), "red").save(source)
    with factory() as db:
        image = models.Image(image_id="1234567890", file_extension="png", file_path=str(source))
        db.add(image)
        db.flush()
        job = jobs.ImageJobQueue.enqueue(db, kind, image_id=image.image_id)
        job_id = job.id
        target = Path(getattr(ImageService, "thumb_path" if kind == "thumbnail" else "preview_path")(image))
        db.commit()
    target.write_bytes(b"previous working derivative")

    @contextmanager
    def context():
        with factory() as db:
            try:
                yield db
                db.commit()
            except BaseException:
                db.rollback()
                raise

    monkeypatch.setattr(jobs, "get_db_context", context)
    stage = jobs.ImagePipeline.stage

    def racing_stage(image, kind):
        result = stage(image, kind)
        # A separate writer can commit while decoding is outside the DB transaction.
        with factory() as db:
            current = db.get(models.Image, image.image_id)
            if change == "version":
                current.updated_at = datetime.utcnow() + timedelta(minutes=1)
            elif change == "delete":
                db.delete(db.get(models.ImageJob, job_id))
                db.delete(current)
                target.unlink()
            elif change == "lease":
                db.get(models.ImageJob, job_id).locked_at = datetime.utcnow() + timedelta(minutes=1)
            elif change == "physical":
                Image.new("RGB", (30, 20), "blue").save(source)
            elif change == "missing":
                source.unlink()
            db.commit()
        return result

    monkeypatch.setattr(jobs.ImagePipeline, "stage", racing_stage)
    if change == "publish_error":
        replace = os.replace

        def failing_publish(source, destination):
            if Path(source).name.startswith("job-"):
                raise OSError("synthetic publication failure")
            return replace(source, destination)

        monkeypatch.setattr(os, "replace", failing_publish)
    assert jobs.ImageJobWorker().run_once()
    with factory() as db:
        current_job = db.get(models.ImageJob, job_id)
        if change == "none":
            assert current_job.status == "completed"
            with Image.open(target) as preview:
                assert preview.size == (20, 15)
        elif change == "delete":
            assert current_job is None and not target.exists()
        else:
            assert target.read_bytes() == b"previous working derivative"
            assert current_job.status == ("running" if change == "lease" else "retry")
    assert not list((target.parent / ".staging").iterdir())
    engine.dispose()


def test_stale_stage_cleanup_respects_live_os_lease(tmp_path, monkeypatch):
    from app.file_operations import FileOperation, _lease
    monkeypatch.setattr(settings, "THUMB_PATH", str(tmp_path))
    monkeypatch.setattr(settings, "PREVIEW_PATH", str(tmp_path))
    path = tmp_path / ".staging" / "job-crashed.webp"
    path.parent.mkdir()
    path.write_bytes(b"staged")
    os.utime(path, (time.time() - 86400, time.time() - 86400))
    lease = FileOperation(path, {}, None, _lease(path))
    jobs.ImagePipeline.clean_stale_stages()
    assert path.exists()
    lease.release()
    jobs.ImagePipeline.clean_stale_stages()
    assert not path.exists() and not path.with_suffix(".lock").exists()
