"""Persistent jobs. Claim, external work and final writes use separate transactions."""

import hashlib
import shutil
import threading
from datetime import datetime, timedelta
from pathlib import Path

from PIL import Image as PILImage
from sqlalchemy import select, update

from ... import models
from ...config import settings
from ...database import get_db_context
from ...jobs import ImageJobQueue
from ...services import ImageService
from ...storage import get_image_storage
from . import service
from .provider import PixivError, download
from .recommendations import TagIndex

ACCOUNT_LOCK = threading.RLock()
ACTIVE = ("queued", "running", "retry", "awaiting_duplicate")


def enqueue(db, actor_id, kind, payload=None, key=None):
    account = service.require_account(db)
    service.require_actor(db, actor_id)
    if key:
        key = f"{account.revision}:{kind}:{key}"
        existing = db.query(models.PixivJob).filter_by(dedupe_key=key).first()
        if existing:
            if kind in ("import", "cache") and existing.payload != (payload or {}):
                raise PixivError("idempotency_conflict")
            return existing
    if kind not in ("import", "cache"):
        active = (
            db.query(models.PixivJob)
            .filter(
                models.PixivJob.account_revision == account.revision,
                models.PixivJob.kind == kind,
                models.PixivJob.status.in_(("queued", "running", "retry")),
            )
            .all()
        )
        for existing in active:
            if all(
                existing.payload.get(k, default) == (payload or {}).get(k, default)
                for k, default in (("restrict", "public"), ("mode", "combined"))
            ):
                return existing
    job = models.PixivJob(
        actor_id=actor_id, account_revision=account.revision, kind=kind, payload=payload or {}, dedupe_key=key
    )
    db.add(job)
    db.flush()
    return job


def source_for(db, pid, page):
    from ...pixiv_metadata import library_pixiv_image
    return library_pixiv_image(db, pid, page)


def validate_draft(db, draft):
    service.require_actor(db, draft["actor_id"])
    for name, cls in (
        ("group_ids", models.Group),
        ("character_ids", models.Character),
        ("feature_tag_ids", models.FeatureTag),
    ):
        ids = set(draft.get(name, []))
        if ids and db.query(cls).filter(cls.id.in_(ids)).count() != len(ids):
            raise PixivError("invalid_tags")
    if not draft.get("group_ids"):
        raise PixivError("group_required")


def page_draft(draft, page):
    """Never fall back to work-level character tags for a split import."""
    if draft.get("import_mode", "merged") != "split":
        return draft
    tags = draft.get("page_drafts", {}).get(str(page))
    if not isinstance(tags, dict):
        raise PixivError("invalid_page_draft")
    return {**tags, "actor_id": draft["actor_id"]}


def validate_import_draft(db, draft):
    if draft.get("import_mode", "merged") not in ("merged", "split"):
        raise PixivError("invalid_page_draft")
    if draft.get("import_mode") == "split":
        if not set(draft["pages"]).issubset(draft.get("confirmed_pages", [])):
            raise PixivError("pages_unconfirmed")
        for page in draft["pages"]:
            validate_draft(db, page_draft(draft, page))
    else:
        validate_draft(db, draft)


def add_source(db, image_id, pid, page, sha, art, *, apply_tag_matches=True):
    from ...pixiv_metadata import apply_metadata

    image = db.get(models.Image, image_id)
    apply_metadata(db, image, art, page, apply_tag_matches=apply_tag_matches)
    db.add(
        models.PixivImageSource(
            image_id=image_id,
            work_id=pid,
            page_index=page,
            sha256=sha,
            metadata_json={**art, "url": f"https://www.pixiv.net/artworks/{pid}"},
        )
    )


def import_pages(provider, job_id, revision, actor_id, draft):
    from . import cart

    if draft.get("cart_id"):
        with get_db_context() as db:
            item = cart.require_item(db, draft["cart_id"], revision, actor_id)
            art = dict(item.metadata_json)
            if item.pid != draft["pid"] or not set(draft["pages"]).issubset(item.pages):
                raise PixivError("invalid_cart")
    else:
        raw = provider.call("illust_detail", illust_id=draft["pid"]).get("illust")
        art = service.normalize_artwork(raw or {})
    if art is None:
        raise PixivError("artwork_unavailable")
    with get_db_context() as db:
        account = service.require_account(db, revision)
        preferences = account.preferences
        validate_import_draft(db, {**draft, "actor_id": actor_id})
    from .recommendations import allowed

    if not allowed(art, preferences):
        raise PixivError("content_filtered")
    done = []
    for page in draft["pages"]:
        tags = page_draft({**draft, "actor_id": actor_id}, page)
        if page < 0 or page >= art["page_count"] or page >= len(art["originals"]):
            raise PixivError("invalid_page")
        with get_db_context() as db:
            service.require_account(db, revision)
            service.require_actor(db, actor_id)
            db.get(models.PixivJob, job_id).locked_at = datetime.utcnow()
            existing = source_for(db, art["pid"], page)
            if existing:
                done.append({"page": page, "image_id": existing.image_id, "existing": True})
                continue
        stage = Path(settings.DATA_PATH) / "pixiv_ol_staging" / f"{job_id}-{page}.img"
        stage.parent.mkdir(parents=True, exist_ok=True)
        expected_digest = None
        if draft.get("cart_id"):
            with get_db_context() as db:
                item = cart.require_item(db, draft["cart_id"], revision, actor_id)
                cached = cart.cached_path(item, page)
                expected_digest = item.cache[str(page)]["sha256"]
            shutil.copyfile(cached, stage)
        else:
            download(art["originals"][page], stage)
        try:
            with PILImage.open(stage) as image:
                image.verify()
            with PILImage.open(stage) as image:
                width, height = image.size
                if width * height > 50_000_000:
                    raise PixivError("image_too_large")
                extension = {"JPEG": "jpg", "PNG": "png", "WEBP": "webp", "GIF": "gif", "BMP": "bmp"}.get(image.format)
            if not extension:
                raise PixivError("invalid_image")
            digest = hashlib.sha256(stage.read_bytes()).hexdigest()
            if expected_digest and digest != expected_digest:
                raise PixivError("cache_changed")
            perceptual = ImageService.compute_dhash(str(stage))
            with get_db_context() as db:
                service.require_account(db, revision)
                validate_draft(db, tags)
                same = (
                    db.query(models.PixivImageSource)
                    .join(models.Image)
                    .filter(models.PixivImageSource.sha256 == digest)
                    .first()
                )
                duplicates = (
                    db.query(models.Image.image_id, models.Image.perceptual_hash)
                    .filter(
                        models.Image.file_status == "available",
                        models.Image.perceptual_hash.isnot(None),
                        models.Image.groups.any(models.Group.id.in_(tags["group_ids"])),
                    )
                    .all()
                )
                near = [
                    {"image_id": image_id, "distance": ImageService.dhash_distance(perceptual, phash)}
                    for image_id, phash in duplicates
                    if ImageService.dhash_distance(perceptual, phash) <= settings.DUPLICATE_DHASH_DISTANCE
                ]
                decision = draft.get("decisions", {}).get(str(page), {})
                keep = same.image_id if same else None
                if decision.get("action") == "existing":
                    if decision.get("image_id") not in {x["image_id"] for x in near}:
                        raise PixivError("invalid_duplicate_decision")
                    keep = decision["image_id"]
                if not keep and near and decision.get("action") != "different":
                    job = db.get(models.PixivJob, job_id)
                    job.status, job.locked_at = "awaiting_duplicate", None
                    job.result = {
                        "page": page,
                        "duplicates": sorted(near, key=lambda x: x["distance"])[:20],
                        "done": done,
                    }
                    return None
                if keep:
                    if art["x_restrict"]:
                        db.get(models.Image, keep).age_rating = "r18"
                    add_source(db, keep, art["pid"], page, digest if same else "", art, apply_tag_matches=not bool(draft.get("cart_id")))
                    db.flush()
                    done.append({"page": page, "image_id": keep, "existing": True})
                    continue
            image_id = ImageService.generate_image_id()
            key = f"{image_id}.{extension}"
            backend = get_image_storage(settings, local_root=settings.STORE_PATH)
            # Reserve the opaque key before publication for crash compensation.
            with get_db_context() as db:
                service.require_account(db, revision)
                service.require_actor(db, actor_id)
                job = db.get(models.PixivJob, job_id)
                job.result = {"done": done, "publishing_key": key}
            stored = backend.put_file(stage, key, move=False)
            try:
                with get_db_context() as db:
                    service.require_account(db, revision)
                    validate_draft(db, tags)
                    if source_for(db, art["pid"], page):
                        raise PixivError("source_conflict")
                    feature_ids = list(tags.get("feature_tag_ids", []))
                    index = TagIndex(db)
                    for name in tags.get("new_tags", []):
                        matched = index.match([{"name": name}])
                        if matched["feature_tag_ids"]:
                            feature_ids.extend(matched["feature_tag_ids"])
                        elif matched["group_ids"] or matched["character_ids"] or matched["conflicts"]:
                            raise PixivError("tag_conflict")
                        else:
                            tag = models.FeatureTag(name=name)
                            db.add(tag)
                            db.flush()
                            feature_ids.append(tag.id)
                    rating = "r18" if art["x_restrict"] else tags.get("age_rating", "all")
                    image = models.Image(
                        image_id=image_id,
                        pid=art["pid"],
                        description=art["title"],
                        age_rating=rating,
                        original_filename=f"{art['pid']}_p{page}.{extension}",
                        file_extension=extension,
                        file_path=stored.locator,
                        file_size=stage.stat().st_size,
                        width=width,
                        height=height,
                        file_status="available",
                        file_checked_at=datetime.utcnow(),
                        perceptual_hash=perceptual,
                        pixiv_checked_at=datetime.utcnow(),
                        thumb_status="pending",
                        preview_status="pending",
                    )
                    ImageService._apply_tag_relationships(
                        db, image, tags.get("character_ids", []), tags["group_ids"], feature_ids
                    )
                    db.add(image)
                    db.flush()
                    add_source(db, image_id, art["pid"], page, digest, art, apply_tag_matches=not bool(draft.get("cart_id")))
                    for tag_id in set(feature_ids):
                        db.add(
                            models.ImageTagEvidence(
                                image_id=image_id,
                                feature_tag_id=tag_id,
                                source="pixiv_confirmed",
                                confidence=1.0,
                                confirmed_by=actor_id,
                            )
                        )
                    for kind in ("thumbnail", "preview"):
                        ImageJobQueue.enqueue(db, kind, image_id=image_id, dedupe_key=f"{kind}:{image_id}")
                    done.append({"page": page, "image_id": image_id, "existing": False})
                    db.get(models.PixivJob, job_id).result = {"done": done}
            except Exception:
                backend.delete(key)
                raise
        finally:
            stage.unlink(missing_ok=True)
    with get_db_context() as db:
        service.require_account(db, revision)
        actor = service.require_actor(db, actor_id)
        if actor.role == "root" and actor.qq_number == settings.ROOT_QQ:
            feedback = (
                db.query(models.PixivFeedback)
                .filter_by(account_revision=revision, actor_id=actor_id, pid=art["pid"])
                .first()
            )
            if not feedback:
                db.add(
                    models.PixivFeedback(account_revision=revision, actor_id=actor_id, pid=art["pid"], value="imported")
                )
    return {"done": done}


class Worker:
    def __init__(self):
        self.stop_event = threading.Event()
        self.thread = None
        self.last_schedule = 0.0

    def run_once(self):
        with ACCOUNT_LOCK:
            with get_db_context() as db:
                now = datetime.utcnow()
                db.query(models.PixivJob).filter(
                    models.PixivJob.status == "running", models.PixivJob.locked_at < now - timedelta(minutes=30)
                ).update({"status": "retry", "locked_at": None})
                candidate = (
                    select(models.PixivJob.id)
                    .where(models.PixivJob.status.in_(("queued", "retry")), models.PixivJob.available_at <= now)
                    .order_by(models.PixivJob.available_at, models.PixivJob.id)
                    .limit(1)
                    .scalar_subquery()
                )
                job_id = db.execute(
                    update(models.PixivJob)
                    .where(models.PixivJob.id == candidate, models.PixivJob.status.in_(("queued", "retry")))
                    .values(status="running", locked_at=now, attempts=models.PixivJob.attempts + 1)
                    .returning(models.PixivJob.id)
                ).scalar_one_or_none()
                if not job_id:
                    return False
                job = db.get(models.PixivJob, job_id)
                actor_id, revision, kind, payload = job.actor_id, job.account_revision, job.kind, job.payload
                publishing = job.result.get("publishing_key")
            provider = None
            try:
                if publishing:
                    backend = get_image_storage(settings, local_root=settings.STORE_PATH)
                    with get_db_context() as db:
                        published = db.get(models.Image, Path(publishing).stem)
                    if not published:
                        backend.delete(publishing)
                if not (kind == "import" and payload.get("cart_id")):
                    provider = service.client_for_job(actor_id, revision)
                if kind == "sync":
                    result = service.sync_feed(provider, revision, actor_id, payload.get("restrict", "public"))
                elif kind == "following":
                    result = service.sync_following(provider, revision, actor_id, payload.get("restrict", "public"))
                elif kind == "recommendations":
                    result = service.refresh_candidates(provider, revision, actor_id, payload.get("mode", "combined"))
                elif kind == "browse_recommendations":
                    result = service.refresh_candidates(
                        provider, revision, actor_id, payload.get("mode", "combined"), continuation=True
                    )
                elif kind == "browse_feed":
                    with get_db_context() as db:
                        account = service.require_account(db, revision)
                        restrictions = (
                            ["public", "private"] if account.preferences.get("private_following") else ["public"]
                        )
                    continuations = [
                        service.continue_feed(provider, revision, actor_id, restrict) for restrict in restrictions
                    ]
                    result = {
                        "count": sum(part["count"] for part in continuations),
                        "more": any(part["more"] for part in continuations),
                    }
                elif kind == "import":
                    result = import_pages(provider, job_id, revision, actor_id, payload)
                elif kind == "cache":
                    from .cart import cache_pages

                    result = cache_pages(provider, job_id, revision, actor_id, payload)
                else:
                    raise PixivError("invalid_job")
                if result is not None:
                    with get_db_context() as db:
                        service.require_account(db, revision)
                        job = db.get(models.PixivJob, job_id)
                        job.status = "partial" if result.get("partial") else "completed"
                        job.result, job.error, job.locked_at = result, None, None
                        if kind != "import":
                            job.dedupe_key = None
                        if kind == "import" and payload.get("cart_id"):
                            item = db.get(models.PixivCartItem, payload["cart_id"])
                            if item:
                                db.delete(item)
                    if kind == "import" and payload.get("cart_id"):
                        from .cart import cleanup

                        cleanup(payload["cart_id"])
            except Exception as exc:
                code = exc.code if isinstance(exc, PixivError) else "processing_failed"
                with get_db_context() as db:
                    job = db.get(models.PixivJob, job_id)
                    if job and job.status != "cancelled":
                        job.error, job.locked_at = code, None
                        permanent = code in {
                            "reauth_required",
                            "permission_revoked",
                            "account_changed",
                            "invalid_tags",
                            "group_required",
                            "content_filtered",
                            "invalid_page",
                            "artwork_unavailable",
                            "cart_removed",
                            "invalid_cart",
                            "cache_missing",
                            "cache_changed",
                            "cache_full",
                        }
                        job.status = "failed" if permanent or job.attempts >= 3 else "retry"
                        job.available_at = datetime.utcnow() + timedelta(
                            seconds=max(getattr(exc, "delay", 0), min(300, 30 * job.attempts))
                        )
                        if job.status == "failed" and kind != "import":
                            job.dedupe_key = None
                        account = db.get(models.PixivAccount, 1)
                        if account and account.revision == revision and code == "reauth_required":
                            account.status = "reauth_required"
                        if payload.get("cart_id"):
                            item = db.get(models.PixivCartItem, payload["cart_id"])
                            if item:
                                item.status = (
                                    "failed" if kind == "cache" else ("importing" if job.status == "retry" else "ready")
                                )
            finally:
                if provider:
                    provider.close()
            return True

    def schedule(self):
        from .cart import cleanup_orphans

        cleanup_orphans()
        with get_db_context() as db:
            account = db.get(models.PixivAccount, 1)
            if not account or account.status != "connected":
                return
            service.require_actor(db, account.owner_id)
            for restrict in (["public", "private"] if account.preferences.get("private_following") else ["public"]):
                for kind, period in (("sync", settings.PIXIV_OL_SYNC_SECONDS), ("following", 86400)):
                    state = account.sync_state.get(f"{'feed' if kind == 'sync' else 'following'}_{restrict}", {})
                    last = state.get("last_success")
                    if (
                        last
                        and (datetime.utcnow() - service.iso_date(last)).total_seconds() < period
                        and not state.get("cursor")
                    ):
                        continue
                    enqueue(db, account.owner_id, kind, {"restrict": restrict}, f"scheduled:{restrict}")

    def _run(self):
        import time

        while not self.stop_event.is_set():
            try:
                if time.monotonic() - self.last_schedule > 60:
                    self.schedule()
                    self.last_schedule = time.monotonic()
                if self.run_once():
                    continue
            except Exception:
                # Never log exception bodies: third-party errors can contain credentials.
                pass
            self.stop_event.wait(2)

    def start(self):
        if self.thread and self.thread.is_alive():
            return
        # The documented single-process runner has no surviving lease owner after restart.
        with get_db_context() as db:
            db.query(models.PixivJob).filter_by(status="running").update(
                {"status": "retry", "locked_at": None, "available_at": datetime.utcnow()}
            )
            db.query(models.PixivLoginSession).filter(
                models.PixivLoginSession.status.in_(("browser", "cli", "exchanging"))
            ).update({"status": "failed", "error": "login_interrupted", "verifier": ""})
        self.stop_event.clear()
        self.thread = threading.Thread(target=self._run, name="pixiv_ol_worker", daemon=True)
        self.thread.start()

    def stop(self):
        from .cli_login import shutdown

        shutdown()
        self.stop_event.set()
        if self.thread:
            self.thread.join(timeout=5)


worker = Worker()
