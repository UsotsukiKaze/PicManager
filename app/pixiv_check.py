"""Administrator review of library Pixiv identity, metadata and optional missing pages."""

import hashlib
import secrets
from datetime import datetime, timedelta
from pathlib import Path
from sqlalchemy import or_

from . import models
from .database import get_db_context
from .pixiv import PixivUpgradeService, PixivLookupError
from .pixiv_metadata import split_pid, canonical_pid, apply_metadata
from .services import ImageService
from .integrations.pixiv_ol import service, jobs
from .integrations.pixiv_ol.provider import PixivError, download


class ArtworkDenied(PixivError):
    """A denied detail lookup, scoped to this exact image/PID and account."""
    def __init__(self, checkpoint):
        self.checkpoint = checkpoint
        super().__init__("access_deny")


class ArtworkClient:
    def __init__(self, art):
        self.art = art

    def pages(self, pid):
        return [
            {
                "urls": {
                    "original": url,
                    "regular": (
                        (self.art.get("page_previews") or [])[page]
                        if page < len(self.art.get("page_previews") or [])
                        else url
                    ),
                },
                "width": self.art.get("width", 0),
                "height": self.art.get("height", 0),
            }
            for page, url in enumerate(self.art["originals"])
        ]

    def download(self, url, path):
        from PIL import Image

        download(url, path)
        with Image.open(path) as image:
            return image.width, image.height, path.stat().st_size


def snapshot(image):
    stat = Path(ImageService.image_full_path(image)).stat()
    return {"pid": image.pid, "size": stat.st_size, "mtime": stat.st_mtime_ns}


def needs_check():
    return or_(models.Image.pixiv_checked_at.is_(None), ~models.Image.pixiv_metadata.has(),
               models.Image.pixiv_metadata.has(models.PixivImageMetadata.status == "unavailable"))


def is_complete(image):
    return bool(image.pixiv_checked_at and image.pixiv_metadata and image.pixiv_metadata.status != "unavailable")


def pending(db):
    rows = (
        db.query(models.Image)
        .outerjoin(models.PixivImageMetadata)
        .filter(
            models.Image.file_status == "available",
            models.Image.pid.isnot(None),
            needs_check(),
        )
        .order_by(models.Image.created_at, models.Image.image_id)
        .all()
    )
    return [image for image in rows if split_pid(image.pid) and ImageService.image_file_exists(image)]


def record_page(db, image, art, page):
    apply_metadata(db, image, art, page, apply_tag_matches=False)
    db.flush()
    source = db.query(models.PixivImageSource).filter_by(provider="pixiv", work_id=art["pid"], page_index=page).first()
    if source is None:
        source = models.PixivImageSource(
            image_id=image.image_id,
            provider="pixiv",
            work_id=art["pid"],
            page_index=page,
            sha256=hashlib.sha256(Path(ImageService.image_full_path(image)).read_bytes()).hexdigest(),
            metadata_json=art,
        )
        db.add(source)
    return source


def scan_next(actor_id):
    with get_db_context() as db:
        service.require_actor(db, actor_id)
        from .visual_similarity import index_missing_batch
        fingerprinted = index_missing_batch(db)
        if fingerprinted['processed']:
            return {"status":"fingerprinted",**fingerprinted}
        from .tag_mappings import sync_cached_exact
        mapped = sync_cached_exact(db)
        from .pixiv_metadata import backfill_checked_tags
        backfill_checked_tags(db)
        rows = pending(db)
        if not rows:
            return {"status": "complete", "remaining": 0, "auto_mappings": mapped}
        image_id = rows[0].image_id
    return scan_image(actor_id, image_id, remaining=len(rows))


def scan_image(actor_id, image_id, *, remaining=1, revision=None, client=None, guard=None, denial=None):
    """One independent image check; queue leases are checked before library writes."""
    with get_db_context() as db:
        service.require_actor(db, actor_id)
        if guard:
            guard(db)
        image = db.get(models.Image, image_id)
        if not image or image.file_status != "available" or not split_pid(image.pid) or not ImageService.image_file_exists(image):
            return {"status": "skipped", "remaining": max(0, remaining - 1)}
        if is_complete(image):
            return {"status": "skipped", "remaining": max(0, remaining - 1)}
        account = service.require_account(db, revision)
        revision, before = account.revision, snapshot(image)
        if guard:
            review = db.query(models.PixivCheckReview).filter_by(
                actor_id=actor_id, image_id=image_id, account_revision=revision, resolved=None,
            ).filter(models.PixivCheckReview.expires_at > datetime.utcnow()).first()
            if review and review.snapshot == before:
                return review_json(db, review, remaining=remaining)
        work_id, explicit_page = split_pid(image.pid)
        current_hash = ImageService.compute_dhash(ImageService.image_full_path(image))
        current_width, current_height = PixivUpgradeService._image_dimensions(image)
    PixivUpgradeService.throttle_scan()
    own_client = client is None
    if own_client:
        # Only credential rotation needs serialization. Each worker owns its HTTP session.
        with jobs.ACCOUNT_LOCK:
            client = service.client_for_job(actor_id, revision)
    try:
        raw = client.call("illust_detail", illust_id=work_id).get("illust")
        art = service.normalize_artwork(raw or {})
        if not art:
            # Invisible works need three matching denied lookups before clearing.
            raise PixivError("access_deny" if isinstance(raw, dict) and raw.get("visible") is False else "artwork_unsupported")
        art["width"], art["height"] = int(raw.get("width") or 0), int(raw.get("height") or 0)
        service.save_artworks(revision, [raw], "library_check", actor_id)
    except PixivError as exc:
        if exc.code in {"access_deny", "access_denied"}:
            previous = denial or {}
            count = (previous.get("count", 0) if previous.get("snapshot") == before
                     and previous.get("revision") == revision else 0) + 1
            checkpoint = {"status": "denied_retry", "count": count, "snapshot": before, "revision": revision}
            if count < 3:
                raise ArtworkDenied(checkpoint) from None
            invalid_reason = "access_deny"
        elif exc.code == "artwork_unavailable":
            invalid_reason = "artwork_unavailable"
        else:
            raise
        art = None
    finally:
        if own_client:
            client.close()
    if art is None:
        with get_db_context() as db:
            service.require_actor(db, actor_id)
            if guard:
                guard(db)
            service.require_account(db, revision)
            image = db.get(models.Image, image_id)
            if not image or snapshot(image) != before:
                raise PixivError("image_changed")
            image.pid, image.pixiv_checked_at, image.pixiv_metadata = None, None, None
            image.pixiv_sources = [source for source in image.pixiv_sources if source.provider != "pixiv"]
            db.query(models.PixivCheckReview).filter_by(image_id=image_id, resolved=None).update(
                {"expires_at": datetime.utcnow()}, synchronize_session=False,
            )
        return {"status": "invalid_pid_cleared", "previous_pid": before["pid"], "reason": invalid_reason,
                "remaining": max(0, remaining - 1)}
    larger = (
        art["width"] >= current_width
        and art["height"] >= current_height
        and art["width"] * art["height"] > current_width * current_height
    )
    if art["page_count"] == 1 and not larger:
        with get_db_context() as db:
            service.require_actor(db, actor_id)
            if guard:
                guard(db)
            service.require_account(db, revision)
            image = db.get(models.Image, image_id)
            if not image or snapshot(image) != before:
                raise PixivError("image_changed")
            record_page(db, image, art, 0)
        return {"status": "validated", "pid": canonical_pid(work_id, 0), "remaining": max(0, remaining - 1)}
    suggested = None
    matching = {"status": "manual", "sampled": 0, "failed": 0}
    # Existing explicit pages are shown as suggestions; bare IDs are compared to page samples.
    if explicit_page is not None and explicit_page < art["page_count"]:
        suggested = explicit_page
        matching["status"] = "explicit_page"
    elif art["page_count"] == 1:
        suggested = 0
    else:
        from .config import settings

        root = Path(settings.PENDING_PATH)
        root.mkdir(parents=True, exist_ok=True)
        matches, consecutive_failures = [], 0
        for page, url in enumerate(art.get("page_previews", [])[:50]):
            if guard:
                with get_db_context() as db:
                    guard(db)
            stage = root / f".pixiv-check-{secrets.token_hex(8)}.sample"
            try:
                download(url, stage, limit=5 * 1024 * 1024)
                distance = ImageService.dhash_distance(current_hash, ImageService.compute_dhash(str(stage)))
                matching["sampled"] += 1
                matches.append((distance, page))
                consecutive_failures = 0
            except (PixivError, OSError, ValueError):
                # Page inference is optional. Preserve a manual review even when
                # CDN samples cannot be downloaded/read; never lose this image.
                matching["failed"] += 1
                consecutive_failures += 1
            finally:
                stage.unlink(missing_ok=True)
            if consecutive_failures >= 3:
                break
        matches.sort()
        if matches and matches[0][0] <= settings.PIXIV_UPGRADE_DHASH_DISTANCE:
            if len(matches) == 1 or matches[1][0] > matches[0][0]:
                suggested = matches[0][1]
                matching["status"] = "suggested"
            else:
                matching["status"] = "ambiguous"
        else:
            matching["status"] = "preview_failed" if matching["failed"] else "no_match"
    with get_db_context() as db:
        service.require_actor(db, actor_id)
        if guard:
            guard(db)
        service.require_account(db, revision)
        image = db.get(models.Image, image_id)
        if not image or snapshot(image) != before:
            raise PixivError("image_changed")
        # A legacy HD-only flag is not confirmation of a multi-page identity.
        image.pixiv_checked_at = None
        # Each scan supersedes the previous uncommitted review for this image.
        db.query(models.PixivCheckReview).filter(models.PixivCheckReview.expires_at < datetime.utcnow()).delete(
            synchronize_session=False
        )
        db.query(models.PixivCheckReview).filter_by(image_id=image_id, resolved=None).delete(synchronize_session=False)
        review = models.PixivCheckReview(
            id=secrets.token_hex(24),
            image_id=image_id,
            actor_id=actor_id,
            account_revision=revision,
            snapshot=before,
            artwork={**art, "page_matching": matching},
            suggested_page=suggested,
            expires_at=datetime.utcnow() + (timedelta(days=7) if guard else timedelta(minutes=30)),
        )
        db.add(review)
        db.flush()
        return review_json(db, review, remaining=remaining)


def review_json(db, review, *, remaining=0):
    image = db.get(models.Image, review.image_id)
    art, before = review.artwork, review.snapshot
    work_id, image_id = art["pid"], review.image_id
    imported = {r[0] for r in db.query(models.PixivImageMetadata.page_index).filter_by(work_id=work_id).all()}
    imported.update(r[0] for r in db.query(models.PixivImageSource.page_index).filter_by(work_id=work_id).all())
    return {
        "status": "review",
        "remaining": remaining,
        "review_id": review.id,
        "current": {
            "image_id": image_id,
            "pid": before["pid"],
            "preview_url": f"/resource/originals/{image_id}",
            "group_ids": [g.id for g in image.groups],
        },
        "artwork": {
            k: v for k, v in art.items() if k not in ("originals", "preview", "page_previews", "author_avatar", "page_matching")
        },
        "suggested_page": review.suggested_page,
        "auto_review_safe": art["page_count"] == 1,
        "imported_pages": sorted(imported),
        "page_matching": art.get("page_matching", {"status": "manual"}),
        "original_url": f"/api/pixiv-ol/artworks/{work_id}/original",
    }


def resolve(review_id, actor_id, current_page, pages, upgrade=False):
    with jobs.ACCOUNT_LOCK, get_db_context() as db:
        service.require_actor(db, actor_id)
        review = db.get(models.PixivCheckReview, review_id)
        if not review or review.actor_id != actor_id or review.resolved or review.expires_at <= datetime.utcnow():
            raise PixivError("check_review_expired")
        service.require_account(db, review.account_revision)
        image = db.get(models.Image, review.image_id)
        if not image or snapshot(image) != review.snapshot or is_complete(image):
            raise PixivError("image_changed")
        art = review.artwork
        if not 0 <= current_page < art["page_count"] or any(not 0 <= page < art["page_count"] for page in pages):
            raise PixivError("invalid_page")
        extras = set(pages) - {current_page}
        existing = {r[0] for r in db.query(models.PixivImageMetadata.page_index).filter_by(work_id=art["pid"]).all()}
        existing.update(r[0] for r in db.query(models.PixivImageSource.page_index).filter_by(work_id=art["pid"]).all())
        extras -= existing
        if extras and not image.groups:
            raise PixivError("group_required")
        candidate = None
        if upgrade:
            # Use only the administrator's chosen page, never replace with another page.
            original_pid = image.pid
            image.pid = canonical_pid(art["pid"], current_page)
            try:
                candidate = PixivUpgradeService.find_candidate(image, ArtworkClient(art))
            except PixivLookupError:
                raise PixivError("download_failed") from None
            finally:
                image.pid = original_pid
        source = record_page(db, image, art, current_page)
        enqueued = None
        if extras:
            enqueued = jobs.enqueue(
                db,
                actor_id,
                "import",
                {
                    "pid": art["pid"],
                    "pages": sorted(extras),
                    "group_ids": [g.id for g in image.groups],
                    "character_ids": [c.id for c in image.characters],
                    "feature_tag_ids": [t.id for t in image.feature_tags],
                    "new_tags": [],
                    "age_rating": image.age_rating,
                },
                f"check:{review.id}",
            )
        review.resolved = datetime.utcnow()
        result = {
            "status": "validated",
            "image_id": image.image_id,
            "pid": image.pid,
            "import_job_id": enqueued.id if enqueued else None,
            "pages": sorted(extras),
            "upgraded": False,
        }
        if candidate:
            token = PixivUpgradeService.make_token(image, candidate)
            image.pixiv_checked_at = None
            PixivUpgradeService.resolve(db, token, "replace")
            source = (
                db.query(models.PixivImageSource)
                .filter_by(provider="pixiv", work_id=art["pid"], page_index=current_page)
                .first()
            )
            if source and source.image_id == image.image_id:
                source.sha256 = hashlib.sha256(Path(ImageService.image_full_path(image)).read_bytes()).hexdigest()
            result["upgraded"] = True
        db.query(models.PixivCheckItem).filter_by(review_id=review.id, status="review").update(
            {"status": "completed", "result": result}, synchronize_session=False,
        )
        return result
