"""Durable, bounded Pixiv validation. Reviews never occupy a worker slot."""

import secrets
import threading
import time
from datetime import datetime, timedelta

from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError, OperationalError
from sqlalchemy.orm import aliased

from . import models, pixiv_check
from .config import settings
from .database import get_db_context
from .integrations.pixiv_ol import service
from .integrations.pixiv_ol.provider import PixivError
from .logger import log_error

START_LOCK = threading.Lock()
LEASE_SECONDS = 300
FATAL = {"account_changed", "reauth_required", "permission_revoked", "invalid_encryption_key"}
RETRYABLE = {"external_error", "download_failed", "rate_limited", "access_denied", "check_database_busy"}


def review_query(db, actor_id, revision):
    return db.query(models.PixivCheckReview).join(
        models.Image, models.Image.image_id == models.PixivCheckReview.image_id,
    ).filter(
        models.PixivCheckReview.actor_id == actor_id,
        models.PixivCheckReview.account_revision == revision,
        models.PixivCheckReview.resolved.is_(None),
        models.PixivCheckReview.expires_at > datetime.utcnow(),
        models.Image.file_status == "available",
        pixiv_check.needs_check(),
    )


def start(actor_id):
    with START_LOCK:
        try:
            with get_db_context() as db:
                service.require_actor(db, actor_id)
                account = service.require_account(db)
                active = db.query(models.PixivCheckRun).filter_by(active_key="pixiv-check").first()
                if active:
                    if active.actor_id != actor_id:
                        raise PixivError("check_busy")
                    return {"id": active.id}
                from .tag_mappings import sync_cached_exact
                from .pixiv_metadata import backfill_checked_tags
                sync_cached_exact(db)
                backfill_checked_tags(db)
                held = set()
                for review in review_query(db, actor_id, account.revision).all():
                    image = db.get(models.Image, review.image_id)
                    try:
                        unchanged = pixiv_check.snapshot(image) == review.snapshot
                    except OSError:
                        unchanged = False
                    if unchanged:
                        held.add(image.image_id)
                        image.pixiv_checked_at = None
                    else:
                        review.expires_at = datetime.utcnow()
                run = models.PixivCheckRun(
                    id=secrets.token_hex(16), actor_id=actor_id, account_revision=account.revision,
                    active_key="pixiv-check", workers=max(1, min(6, settings.PIXIV_CHECK_WORKERS)),
                )
                db.add(run)
                db.flush()
                # Fingerprints use one background task, independent from PID network checks.
                db.add(models.PixivCheckItem(run_id=run.id, kind="prepare"))
                for image in pixiv_check.pending(db):
                    if image.image_id not in held:
                        db.add(models.PixivCheckItem(run_id=run.id, image_id=image.image_id))
                return {"id": run.id}
        except IntegrityError:
            # The unique active key also prevents duplicate runs across server processes.
            with get_db_context() as db:
                active = db.query(models.PixivCheckRun).filter_by(active_key="pixiv-check").first()
                if active and active.actor_id == actor_id:
                    return {"id": active.id}
            raise PixivError("check_busy") from None


def guard(db, item_id, lease):
    # Claim the write boundary atomically. Cancellation/lease recovery cannot
    # interleave between this check and the library mutation in this transaction.
    changed = db.execute(update(models.PixivCheckItem).where(
        models.PixivCheckItem.id == item_id, models.PixivCheckItem.status == "running",
        models.PixivCheckItem.lease == lease,
        models.PixivCheckItem.run_id.in_(select(models.PixivCheckRun.id).where(models.PixivCheckRun.status == "running")),
    ).values(locked_at=datetime.utcnow()).execution_options(synchronize_session=False)).rowcount
    if not changed:
        raise PixivError("check_cancelled")
    item = db.get(models.PixivCheckItem, item_id, populate_existing=True)
    run = db.get(models.PixivCheckRun, item.run_id, populate_existing=True) if item else None
    if not item or item.status != "running" or item.lease != lease or not run or run.status != "running":
        raise PixivError("check_cancelled")
    service.require_actor(db, run.actor_id)
    service.require_account(db, run.account_revision)
    return item, run


def settle_run(db, run):
    active = db.query(models.PixivCheckItem.id).filter(
        models.PixivCheckItem.run_id == run.id, models.PixivCheckItem.status.in_(("queued", "running")),
    ).first()
    if run.status == "running" and not active:
        run.status, run.active_key, run.finished_at = "completed", None, datetime.utcnow()


def claim():
    with get_db_context() as db:
        if not db.query(models.PixivCheckRun.id).filter_by(status="running").first():
            return None  # Avoid three idle UPDATE loops competing with maintenance.
        cutoff = datetime.utcnow() - timedelta(seconds=LEASE_SECONDS)
        db.query(models.PixivCheckItem).filter(
            models.PixivCheckItem.status == "running", models.PixivCheckItem.locked_at < cutoff,
        ).update({"status": "queued", "lease": None, "locked_at": None}, synchronize_session=False)
        running = aliased(models.PixivCheckItem)
        slots = select(func.count(running.id)).where(
            running.run_id == models.PixivCheckRun.id, running.status == "running",
        ).correlate(models.PixivCheckRun).scalar_subquery()
        candidate = select(models.PixivCheckItem.id).join(models.PixivCheckRun).where(
            models.PixivCheckItem.status == "queued",
            models.PixivCheckItem.available_at <= datetime.utcnow(),
            models.PixivCheckRun.status == "running", slots < models.PixivCheckRun.workers,
        ).order_by(models.PixivCheckItem.id).limit(1).scalar_subquery()
        lease = secrets.token_hex(16)
        item_id = db.execute(update(models.PixivCheckItem).where(
            models.PixivCheckItem.id == candidate, models.PixivCheckItem.status == "queued",
        ).values(status="running", lease=lease, locked_at=datetime.utcnow(),
                 attempts=models.PixivCheckItem.attempts + 1).returning(models.PixivCheckItem.id)).scalar_one_or_none()
        if item_id is None:
            for run in db.query(models.PixivCheckRun).filter_by(status="running").all():
                settle_run(db, run)
            return None
        # Credential/permission failures are settled by run_once, after the claim
        # commits; checking them here would roll back and reclaim forever.
        item = db.get(models.PixivCheckItem, item_id)
        run = db.get(models.PixivCheckRun, item.run_id)
        return {"id": item.id, "lease": lease, "kind": item.kind, "image_id": item.image_id,
                "actor_id": run.actor_id, "revision": run.account_revision, "denial": item.result or {}}


def stop(actor_id, run_id):
    with get_db_context() as db:
        service.require_actor(db, actor_id)
        run = db.get(models.PixivCheckRun, run_id)
        if not run or run.actor_id != actor_id:
            raise PixivError("check_not_found")
        if run.status == "running":
            run.status, run.active_key, run.finished_at = "cancelled", None, datetime.utcnow()
            db.query(models.PixivCheckItem).filter(
                models.PixivCheckItem.run_id == run.id, models.PixivCheckItem.status.in_(("queued", "running")),
            ).update({"status": "cancelled", "lease": None, "locked_at": None}, synchronize_session=False)
    return {"status": "cancelled"}


def status(actor_id, run_id=None, offset=0):
    with get_db_context() as db:
        service.require_actor(db, actor_id)
        query = db.query(models.PixivCheckRun).filter_by(actor_id=actor_id)
        run = query.filter_by(id=run_id).first() if run_id else query.order_by(models.PixivCheckRun.created_at.desc()).first()
        if run_id and not run:
            raise PixivError("check_not_found")
        account = db.get(models.PixivAccount, 1)
        reviews = review_query(db, actor_id, account.revision) if account else None
        count = reviews.count() if reviews is not None else 0
        rows = reviews.order_by(models.PixivCheckReview.id).offset(offset).limit(20).all() if reviews is not None else []
        pending = [{"id": row.id, "pid": row.snapshot.get("pid"), "title": row.artwork.get("title"),
                    "page_count": row.artwork.get("page_count"), "auto_review_safe": row.artwork.get("page_count") == 1}
                   for row in rows]
        import_jobs = db.query(models.PixivJob).filter(
            models.PixivJob.actor_id == actor_id, models.PixivJob.kind == "import",
            models.PixivJob.account_revision == (account.revision if account else ""),
            models.PixivJob.dedupe_key.like(f"{account.revision if account else ''}:import:check:%"),
            models.PixivJob.status.notin_(("completed", "cancelled")),
        ).order_by(models.PixivJob.id.desc())
        imports = [{"id": job.id, "pid": job.payload.get("pid"), "pages": job.payload.get("pages", []),
                    "status": job.status, "error": job.error, "done": len(job.result.get("done", [])),
                    "page": job.result.get("page"), "duplicates": job.result.get("duplicates", [])[:20]}
                   for job in import_jobs.limit(20)]
        supplement = {"imports": imports, "import_count": import_jobs.count()}
        if not run:
            return {"run": None, "reviews": pending, "review_count": count, **supplement}
        counts = dict(db.query(models.PixivCheckItem.status, func.count()).filter_by(run_id=run.id)
                      .group_by(models.PixivCheckItem.status).all())
        errors = [{"image_id": row.image_id, "error": row.error} for row in db.query(models.PixivCheckItem)
                  .filter_by(run_id=run.id, status="failed").order_by(models.PixivCheckItem.id).limit(10)]
        return {"run": {"id": run.id, "status": run.status, "workers": run.workers,
                        "total": sum(counts.values()), "counts": counts, "fingerprints": run.fingerprints,
                        "fingerprint_failures": run.fingerprint_failures, "error": run.error, "errors": errors,
                        "invalid_pids": db.query(models.PixivCheckItem).filter_by(run_id=run.id).filter(
                            models.PixivCheckItem.result["status"].as_string() == "invalid_pid_cleared").count()},
                "reviews": pending, "review_count": count, **supplement}


def get_review(actor_id, review_id):
    with get_db_context() as db:
        service.require_actor(db, actor_id)
        account = service.require_account(db)
        review = review_query(db, actor_id, account.revision).filter(models.PixivCheckReview.id == review_id).first()
        if not review:
            raise PixivError("check_review_expired")
        image = db.get(models.Image, review.image_id)
        if pixiv_check.snapshot(image) != review.snapshot:
            raise PixivError("image_changed")
        return pixiv_check.review_json(db, review)


class PixivCheckWorker:
    def __init__(self):
        self.stop_event = threading.Event()
        self.threads = []
        self.local = threading.local()
        self.last_error_log = {}

    def close_client(self):
        client = getattr(self.local, "client", None)
        if client:
            client.close()
        self.local.client = self.local.key = None

    def client(self, task):
        key = (task["actor_id"], task["revision"])
        if getattr(self.local, "key", None) != key:
            self.close_client()
            with get_db_context() as db:
                self.check_guard(db, task)
            self.local.client = service.client_for_job(*key)
            self.local.key = key
        return self.local.client

    def prepare(self, task):
        from .visual_similarity import index_missing_batch
        while not self.stop_event.is_set():
            with get_db_context() as db:
                item, run = guard(db, task["id"], task["lease"])
                result = index_missing_batch(db, limit=1)
                run.fingerprints += result["processed"]
                run.fingerprint_failures += result["failed"]
            if not result["processed"]:
                return {"status": "prepared"}
        raise PixivError("check_cancelled")

    def check_guard(self, db, task):
        if self.stop_event.is_set():
            raise PixivError("check_cancelled")
        return guard(db, task["id"], task["lease"])

    def run_once(self):
        task = claim()
        if not task:
            self.close_client()
            return False
        error, result, denial = None, None, None
        try:
            if task["kind"] == "prepare":
                result = self.prepare(task)
            else:
                for refresh in range(2):
                    try:
                        result = pixiv_check.scan_image(
                            task["actor_id"], task["image_id"], revision=task["revision"], client=self.client(task),
                            guard=lambda db: self.check_guard(db, task),
                            denial=task["denial"],
                        )
                        break
                    except PixivError as exc:
                        if exc.code != "reauth_required" or refresh:
                            raise
                        # Renew an expired access token once using the stored refresh token.
                        self.close_client()
        except Exception as exc:
            if isinstance(exc, pixiv_check.ArtworkDenied):
                denial = exc.checkpoint
            error = (exc.code if isinstance(exc, PixivError) else
                     "check_database_busy" if isinstance(exc, (IntegrityError, OperationalError)) else
                     "check_processing_failed")
            self.close_client()
            if error != "check_cancelled" and denial is None:
                log_error(f"Pixiv check item failed: item={task['id']}, error={error}")
        with get_db_context() as db:
            item = db.get(models.PixivCheckItem, task["id"])
            run = db.get(models.PixivCheckRun, item.run_id) if item else None
            if not item or item.status != "running" or item.lease != task["lease"]:
                return True
            item.lease = item.locked_at = None
            if error:
                item.error = error
                # A different error breaks the sequence; attempts alone cannot
                # establish three consecutive denied detail lookups.
                item.result = denial
                if error == "check_cancelled" and self.stop_event.is_set() and run.status == "running":
                    item.status, item.available_at = "queued", datetime.utcnow()
                    item.attempts = max(0, item.attempts - 1)
                elif (denial is not None or error in RETRYABLE and item.attempts < 3) and run.status == "running":
                    item.status = "queued"
                    item.available_at = datetime.utcnow() + timedelta(seconds=30 if error == "rate_limited" else 2 ** min(item.attempts, 3))
                else:
                    item.status = "failed"
                if error in FATAL:
                    run.status, run.active_key, run.error, run.finished_at = "failed", None, error, datetime.utcnow()
                    db.query(models.PixivCheckItem).filter(
                        models.PixivCheckItem.run_id == run.id, models.PixivCheckItem.status.in_(("queued", "running")),
                        models.PixivCheckItem.id != item.id,
                    ).update({"status": "cancelled", "lease": None, "locked_at": None}, synchronize_session=False)
            else:
                item.result, item.error = result, None
                item.status = "review" if result["status"] == "review" else "completed"
                item.review_id = result.get("review_id")
                if result["status"] == "invalid_pid_cleared" and not db.query(models.PixivCheckItem.id).filter_by(
                    run_id=run.id, kind="prepare", status="queued",
                ).first():
                    # A previously identified image is now eligible for similarity
                    # indexing, even if the initial preparation task already ended.
                    db.add(models.PixivCheckItem(run_id=run.id, kind="prepare"))
            db.flush()
            settle_run(db, run)
        return True

    def _run(self):
        try:
            while not self.stop_event.is_set():
                try:
                    if not self.run_once():
                        self.stop_event.wait(1)
                except Exception as exc:
                    category = "database_busy" if isinstance(exc, OperationalError) else type(exc).__name__
                    now = time.monotonic()
                    previous = self.last_error_log.get(threading.get_ident(), 0)
                    if now - previous >= 30 or not previous:
                        log_error(f"Pixiv check queue temporarily unavailable: error={category}")
                        self.last_error_log[threading.get_ident()] = now
                    self.stop_event.wait(2)
        finally:
            self.close_client()

    def start(self):
        if any(thread.is_alive() for thread in self.threads):
            return
        self.stop_event.clear()
        self.threads = [threading.Thread(target=self._run, name=f"pixiv_check_{i}", daemon=True)
                        for i in range(max(1, min(6, settings.PIXIV_CHECK_WORKERS)))]
        for thread in self.threads:
            thread.start()

    def stop(self):
        self.stop_event.set()
        for thread in self.threads:
            thread.join(timeout=2)


worker = PixivCheckWorker()
