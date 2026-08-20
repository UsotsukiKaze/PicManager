"""Durable image job queue and background worker."""

from __future__ import annotations

import json
import tempfile
import threading
from datetime import datetime, timedelta
from pathlib import Path

from sqlalchemy import select, update

from . import models
from .config import settings
from .database import get_db_context
from .logger import log_error, log_info
from .services import ImageService
from .storage import get_image_storage


class ImageJobQueue:
    ACTIVE = ("queued", "retry", "running")

    @staticmethod
    def enqueue(db, job_type: str, *, image_id: str | None = None, payload: dict | None = None,
                dedupe_key: str | None = None, max_attempts: int = 5) -> models.ImageJob:
        if dedupe_key:
            existing = db.query(models.ImageJob).filter(
                models.ImageJob.dedupe_key == dedupe_key,
                models.ImageJob.status.in_(ImageJobQueue.ACTIVE),
            ).first()
            if existing:
                return existing
        job = models.ImageJob(
            job_type=job_type,
            image_id=image_id,
            payload=json.dumps(payload or {}),
            dedupe_key=dedupe_key,
            status="queued",
            max_attempts=max(1, int(max_attempts)),
            available_at=datetime.utcnow(),
        )
        db.add(job)
        db.flush()
        return job

    @staticmethod
    def recover_stale(db, *, stale_seconds: int) -> int:
        cutoff = datetime.utcnow() - timedelta(seconds=max(1, int(stale_seconds)))
        jobs = db.query(models.ImageJob).filter(
            models.ImageJob.status == "running",
            models.ImageJob.locked_at < cutoff,
        ).all()
        for job in jobs:
            job.status = "retry"
            job.available_at = datetime.utcnow()
            job.locked_at = None
            job.last_error = "worker lease expired"
        return len(jobs)

    @staticmethod
    def claim(db) -> models.ImageJob | None:
        now = datetime.utcnow()
        candidate = select(models.ImageJob.id).where(
            models.ImageJob.status.in_(("queued", "retry")),
            models.ImageJob.available_at <= now,
        ).order_by(models.ImageJob.available_at, models.ImageJob.id).limit(1).scalar_subquery()
        claimed_id = db.execute(
            update(models.ImageJob)
            .where(
                models.ImageJob.id == candidate,
                models.ImageJob.status.in_(("queued", "retry")),
            )
            .values(
                status="running",
                attempts=models.ImageJob.attempts + 1,
                locked_at=now,
            )
            .returning(models.ImageJob.id)
        ).scalar_one_or_none()
        if claimed_id is None:
            return None
        return db.get(models.ImageJob, claimed_id, populate_existing=True)

    @staticmethod
    def complete(job: models.ImageJob) -> None:
        job.status = "completed"
        job.locked_at = None
        job.last_error = None

    @staticmethod
    def fail(job: models.ImageJob, error: Exception) -> None:
        job.last_error = str(error)[:4000]
        job.locked_at = None
        if job.attempts >= job.max_attempts:
            job.status = "failed"
            return
        job.status = "retry"
        delay = min(300, 2 ** max(0, job.attempts - 1))
        job.available_at = datetime.utcnow() + timedelta(seconds=delay)


class ImagePipeline:
    @staticmethod
    def _r2_object_key(locator: str) -> str:
        return locator.split("/", 3)[-1]

    @staticmethod
    def generate_thumbnail(db, image: models.Image) -> None:
        if str(image.file_path or "").startswith("r2://"):
            backend = get_image_storage(settings)
            suffix = f".{image.file_extension or 'img'}"
            with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as temp:
                staged = Path(temp.name)
            try:
                backend.download_file(ImagePipeline._r2_object_key(image.file_path), staged)
                ImageService.write_thumbnail(str(staged), ImageService.thumb_path(image))
                image.thumb_status = ImageService.THUMB_READY
            finally:
                staged.unlink(missing_ok=True)
            return
        if not ImageService.ensure_thumbnail(image):
            raise RuntimeError(f"Thumbnail generation failed for {image.image_id}")

    @staticmethod
    def handle(db, job: models.ImageJob) -> None:
        if job.job_type != "thumbnail":
            raise ValueError(f"Unknown image job: {job.job_type}")
        image = db.query(models.Image).filter(models.Image.image_id == job.image_id).first()
        if not image:
            raise ValueError(f"Image no longer exists: {job.image_id}")
        ImagePipeline.generate_thumbnail(db, image)


class ImageJobWorker:
    def __init__(self, *, poll_seconds: float | None = None):
        self.poll_seconds = max(0.1, float(poll_seconds or settings.IMAGE_JOB_POLL_SECONDS))
        self.stop_event = threading.Event()
        self.thread: threading.Thread | None = None

    def run_once(self) -> bool:
        with get_db_context() as db:
            ImageJobQueue.recover_stale(db, stale_seconds=settings.IMAGE_JOB_STALE_SECONDS)
            job = ImageJobQueue.claim(db)
            if not job:
                return False
            try:
                ImagePipeline.handle(db, job)
                ImageJobQueue.complete(job)
            except Exception as exc:
                ImageJobQueue.fail(job, exc)
                log_error(f"Image job {job.id} failed: {exc}")
            return True

    def _run(self) -> None:
        while not self.stop_event.is_set():
            if not self.run_once():
                self.stop_event.wait(self.poll_seconds)

    def start(self) -> None:
        if self.thread and self.thread.is_alive():
            return
        self.stop_event.clear()
        self.thread = threading.Thread(target=self._run, name="image_job_worker", daemon=True)
        self.thread.start()
        log_info("Image job worker started")

    def stop(self, timeout: float = 5.0) -> None:
        self.stop_event.set()
        if self.thread:
            self.thread.join(timeout=timeout)


image_job_worker = ImageJobWorker()
