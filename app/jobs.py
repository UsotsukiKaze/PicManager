"""Durable image job queue and background worker."""

from __future__ import annotations

import json
import os
import tempfile
import threading
import time
from datetime import datetime, timedelta
from pathlib import Path

from sqlalchemy import select, update

from . import models
from .config import settings
from .database import get_db_context
from .logger import log_error, log_info
from .services import ImageService
from .file_operations import FileOperation, _lease


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
        if db.execute(select(candidate)).scalar_one_or_none() is None:
            return None  # An idle worker must not continually take SQLite's writer.
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
    def generate_thumbnail(db, image: models.Image) -> None:
        if not ImageService.ensure_thumbnail(image):
            raise RuntimeError(f"Thumbnail generation failed for {image.image_id}")

    @staticmethod
    def generate_preview(db, image: models.Image) -> None:
        try:
            with ImageService.source_file(image) as source:
                ImageService.write_preview(str(source), ImageService.preview_path(image))
            image.preview_status = ImageService.THUMB_READY
        except Exception:
            image.preview_status = ImageService.THUMB_FAILED
            raise

    @staticmethod
    def stage(image: models.Image, kind: str):
        if kind not in {"thumbnail", "preview"}:
            raise ValueError("Unknown derivative job")
        target = Path(ImageService.thumb_path(image) if kind == "thumbnail" else ImageService.preview_path(image))
        directory = target.parent / ".staging"
        directory.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(dir=directory, prefix="job-", suffix=".webp", delete=False) as temp:
            staged = Path(temp.name)
        lease = FileOperation(staged, {}, None, _lease(staged))
        try:
            if lease.handle is None:
                raise RuntimeError("Derivative staging lease unavailable")
            with ImageService.source_file(image) as source:
                writer = ImageService.write_thumbnail if kind == "thumbnail" else ImageService.write_preview
                writer(str(source), str(staged))
            return staged, target, lease
        except BaseException:
            staged.unlink(missing_ok=True)
            lease.release()
            raise

    @staticmethod
    def clean_stale_stages():
        cutoff = time.time() - max(60, settings.IMAGE_JOB_STALE_SECONDS * 2)
        for root in {settings.THUMB_PATH, settings.PREVIEW_PATH}:
            for path in (Path(root) / ".staging").glob("job-*.webp"):
                try:
                    if path.stat().st_mtime >= cutoff:
                        continue
                    lease = FileOperation(path, {}, None, _lease(path))
                    if lease.handle is not None:
                        try:
                            path.unlink(missing_ok=True)
                        finally:
                            lease.release()
                except OSError:
                    continue

    @staticmethod
    def handle(db, job: models.ImageJob) -> None:
        image = db.query(models.Image).filter(models.Image.image_id == job.image_id).first()
        if not image:
            raise ValueError(f"Image no longer exists: {job.image_id}")
        if job.job_type == "thumbnail":
            ImagePipeline.generate_thumbnail(db, image)
        elif job.job_type == "preview":
            ImagePipeline.generate_preview(db, image)
        else:
            raise ValueError(f"Unknown image job: {job.job_type}")


class ImageJobWorker:
    def __init__(self, *, poll_seconds: float | None = None):
        self.poll_seconds = max(0.1, float(poll_seconds or settings.IMAGE_JOB_POLL_SECONDS))
        self.stop_event = threading.Event()
        self.thread: threading.Thread | None = None
        self.last_stage_cleanup = 0.0

    def run_once(self) -> bool:
        with get_db_context() as db:
            ImageJobQueue.recover_stale(db, stale_seconds=settings.IMAGE_JOB_STALE_SECONDS)
            job = ImageJobQueue.claim(db)
            if not job:
                return False
            job_id, image_id, job_type, lease = job.id, job.image_id, job.job_type, job.locked_at
        # The claim is committed before disk/network work, releasing SQLite's writer.
        with get_db_context() as db:
            image = db.get(models.Image, image_id)
            if image:
                source_locator, source_version = image.file_path, image.updated_at
                db.expunge(image)
        error = None
        staged = None
        stage_lease = None
        try:
            if image is None:
                raise ValueError("Image no longer exists")
            source_stat = self._source_stat(image)
            staged, target, stage_lease = ImagePipeline.stage(image, job_type)
        except Exception as exc:
            error = exc
        try:
            with get_db_context() as db:
                # Acquire the writer before checking the source and publishing.
                # Concurrent deletion, edits and stale leases cannot pass this guard.
                claimed = db.execute(update(models.ImageJob).where(
                    models.ImageJob.id == job_id,
                    models.ImageJob.status == "running",
                    models.ImageJob.locked_at == lease,
                ).values(locked_at=lease).returning(models.ImageJob.id)).scalar_one_or_none()
                if claimed is None:
                    return True
                job = db.get(models.ImageJob, job_id, populate_existing=True)
                current = db.get(models.Image, image_id)
                if not error:
                    try:
                        if (not current or current.file_path != source_locator
                                or current.updated_at != source_version or self._source_stat(current) != source_stat):
                            error = RuntimeError("Image changed during derivative generation")
                    except OSError as exc:
                        error = exc
                if error:
                    ImageJobQueue.fail(job, error)
                    log_error(f"Image job {job_id} failed")
                else:
                    try:
                        os.replace(staged, target)
                    except OSError as exc:
                        ImageJobQueue.fail(job, exc)
                        log_error(f"Image job {job_id} publication failed")
                    else:
                        if job_type == "thumbnail":
                            current.thumb_status = ImageService.THUMB_READY
                        else:
                            current.preview_status = ImageService.THUMB_READY
                        ImageJobQueue.complete(job)
        finally:
            if staged is not None:
                staged.unlink(missing_ok=True)
            if stage_lease is not None:
                stage_lease.release()
        return True

    @staticmethod
    def _source_stat(image):
        if str(image.file_path or "").startswith("r2://"):
            return None
        stat = Path(ImageService.image_full_path(image)).stat()
        return stat.st_ino, stat.st_size, stat.st_mtime_ns

    def _run(self) -> None:
        while not self.stop_event.is_set():
            try:
                if time.monotonic() - self.last_stage_cleanup >= 300:
                    ImagePipeline.clean_stale_stages()
                    self.last_stage_cleanup = time.monotonic()
                if not self.run_once():
                    self.stop_event.wait(self.poll_seconds)
            except Exception as exc:
                # Claim/commit contention must not terminate the derivative worker.
                # Leases recover an interrupted commit; never log SQL parameters.
                log_error(f"Image job worker temporarily unavailable: type={type(exc).__name__}")
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
