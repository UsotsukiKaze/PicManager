from datetime import datetime, timedelta

from PIL import Image
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app import models, schemas
from app.config import settings
from app.jobs import ImageJobQueue, ImagePipeline
from app.services import ImageService


def _session(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'jobs.db'}")
    models.Base.metadata.create_all(engine)
    return sessionmaker(bind=engine)


def test_jobs_are_durable_deduplicated_and_claimed_in_order(tmp_path):
    Session = _session(tmp_path)
    with Session() as db:
        first = ImageJobQueue.enqueue(db, "thumbnail", image_id=None, dedupe_key="thumbnail:A")
        duplicate = ImageJobQueue.enqueue(db, "thumbnail", image_id=None, dedupe_key="thumbnail:A")
        assert duplicate.id == first.id
        db.commit()

    with Session() as db:
        claimed = ImageJobQueue.claim(db)
        assert claimed is not None
        assert claimed.status == "running"
        assert claimed.attempts == 1
        ImageJobQueue.complete(claimed)
        db.commit()

    with Session() as db:
        persisted = db.query(models.ImageJob).one()
        assert persisted.status == "completed"


def test_failed_jobs_retry_with_backoff_and_stale_leases_recover(tmp_path):
    Session = _session(tmp_path)
    with Session() as db:
        job = ImageJobQueue.enqueue(db, "thumbnail", max_attempts=2)
        db.flush()
        ImageJobQueue.claim(db)
        ImageJobQueue.fail(job, RuntimeError("temporary"))
        assert job.status == "retry"
        assert job.available_at > datetime.utcnow()

        job.status = "running"
        job.locked_at = datetime.utcnow() - timedelta(hours=1)
        assert ImageJobQueue.recover_stale(db, stale_seconds=30) == 1
        assert job.status == "retry"

        job.status = "running"
        job.attempts = 2
        ImageJobQueue.fail(job, RuntimeError("permanent"))
        assert job.status == "failed"


def test_create_image_enqueues_thumbnail_and_pipeline_generates_it(monkeypatch, tmp_path):
    Session = _session(tmp_path)
    resource = tmp_path / "resource"
    store = resource / "store"
    thumbs = resource / "thumbs"
    source = resource / "temp" / "staged.png"
    source.parent.mkdir(parents=True)
    Image.new("RGB", (24, 12), "blue").save(source)
    monkeypatch.setattr(settings, "BASE_DIR", str(tmp_path))
    monkeypatch.setattr(settings, "STORE_PATH", str(store))
    monkeypatch.setattr(settings, "THUMB_PATH", str(thumbs))
    monkeypatch.setattr(settings, "STORAGE_BACKEND", "local")

    with Session() as db:
        image = ImageService.create_image(
            db,
            schemas.ImageCreate(),
            str(source),
            "staged.png",
            "png",
            str(store),
        )
        image_id = image.image_id
        assert image.thumb_status == ImageService.THUMB_PENDING
        assert not source.exists()
        job = db.query(models.ImageJob).filter(models.ImageJob.image_id == image_id).one()
        assert job.status == "queued"

        claimed = ImageJobQueue.claim(db)
        ImagePipeline.handle(db, claimed)
        ImageJobQueue.complete(claimed)
        db.commit()

    assert (thumbs / f"{image_id}.webp").is_file()
    with Session() as db:
        assert db.get(models.Image, image_id).thumb_status == ImageService.THUMB_READY
        assert db.query(models.ImageJob).one().status == "completed"
