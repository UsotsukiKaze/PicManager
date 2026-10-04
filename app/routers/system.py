from fastapi import APIRouter, HTTPException, Request, Query

from .. import schemas
from ..config import settings
from ..database import get_db_context
from ..security.permissions import require_admin_user_id
from ..services import ImageService, SystemService
from ..pixiv import PixivLookupError, PixivUpgradeService

router = APIRouter()


@router.post("/local-check")
def local_check(request: Request, after_id: str = Query("", pattern="^([a-f0-9]{10})?$"), limit: int = Query(200, ge=1, le=500)):
    require_admin_user_id(request)
    from ..local_check import run_batch
    from ..integrations.pixiv_ol.jobs import ACCOUNT_LOCK
    with PixivUpgradeService.LOCK, ACCOUNT_LOCK, ImageService.DUPLICATE_WRITE_LOCK, get_db_context() as db:
        return run_batch(db, after_id, limit)


@router.post("/pixiv-check/next")
def next_pixiv_check(request: Request):
    from .. import pixiv_check
    from ..integrations.pixiv_ol.provider import PixivError
    actor = require_admin_user_id(request)
    try:
        with PixivUpgradeService.LOCK:
            return pixiv_check.scan_next(actor)
    except PixivError as exc:
        raise HTTPException(502, detail=exc.code) from None


@router.post("/pixiv-check/resolve")
def resolve_pixiv_check(body: schemas.PixivCheckResolveRequest, request: Request):
    from .. import pixiv_check
    from ..integrations.pixiv_ol.provider import PixivError
    actor = require_admin_user_id(request)
    try:
        with PixivUpgradeService.LOCK:
            return pixiv_check.resolve(body.review_id, actor, body.current_page, body.pages, body.upgrade)
    except PixivError as exc:
        raise HTTPException(409, detail=exc.code) from None


@router.get("/pixiv-check/{review_id}/original")
def pixiv_check_original(review_id: str, request: Request, page: int = Query(0, ge=0, le=999)):
    from datetime import datetime
    from fastapi.responses import FileResponse
    from .. import models
    from ..integrations.pixiv_ol import service
    from ..integrations.pixiv_ol.viewer import original
    from ..integrations.pixiv_ol.provider import PixivError
    actor = require_admin_user_id(request)
    with get_db_context() as db:
        review = db.get(models.PixivCheckReview, review_id)
        if not review or review.actor_id != actor or review.resolved or review.expires_at <= datetime.utcnow():
            raise HTTPException(404, "校验预览已失效")
        service.require_account(db, review.account_revision)
        art, revision = dict(review.artwork), review.account_revision
    try:
        path, kind = original(art, revision, page)
    except PixivError as exc:
        raise HTTPException(502, detail=exc.code) from None
    return FileResponse(path, media_type=kind, headers={"Cache-Control":"private, no-store"})


@router.get("/status", response_model=schemas.PublicSystemStatus)
def get_system_status():
    """Return the lightweight public counters used by the home page."""
    with get_db_context() as db:
        return SystemService.get_public_status(db)


@router.get("/diagnostics", response_model=schemas.SystemStatus)
def get_system_diagnostics(request: Request):
    """Return storage and maintenance diagnostics to administrators only."""
    require_admin_user_id(request)
    with get_db_context() as db:
        return SystemService.get_system_status(db, settings.STORE_PATH, settings.TEMP_PATH)


@router.get("/cleanup-preview")
def cleanup_preview(request: Request):
    """Preview missing database records, orphan files and thumbnail gaps."""
    require_admin_user_id(request)
    with get_db_context() as db:
        return ImageService.storage_audit(db, settings.STORE_PATH, update_status=False)


@router.post("/sync-image-status")
def sync_image_status(request: Request):
    """Scan storage and persist file/thumb status flags for fast filtering."""
    require_admin_user_id(request)
    with get_db_context() as db:
        return ImageService.storage_audit(db, settings.STORE_PATH, update_status=True)


@router.post("/cleanup")
def cleanup_orphaned_records(request: Request, mode: str = Query("archive", pattern="^(archive|delete)$")):
    """Remove database image records whose files no longer exist."""
    require_admin_user_id(request)
    with get_db_context() as db:
        count = ImageService.cleanup_orphaned_records(db, settings.STORE_PATH, mode=mode)
        action = "Deleted" if mode == "delete" else "Archived"
        return {"message": f"{action} {count} missing image records", "count": count, "mode": mode}


@router.post("/rebuild-thumbnails")
def rebuild_thumbnails(
    request: Request,
    limit: int = Query(200, ge=1, le=2000),
    force: bool = Query(False),
):
    """Generate thumbnails for available images."""
    require_admin_user_id(request)
    with get_db_context() as db:
        result = ImageService.rebuild_missing_thumbnails(db, limit=limit, force=force)
        return {
            "message": (
                f"Processed {result['processed']} thumbnails, "
                f"{result['ready']} ready, {result['failed']} failed"
            ),
            **result,
        }


@router.post("/scan-store-orphans")
def scan_store_orphans(request: Request):
    """Move image files that are not referenced by the database back to temp."""
    require_admin_user_id(request)
    with get_db_context() as db:
        moved = ImageService.move_orphaned_files_to_temp(db, settings.STORE_PATH, settings.TEMP_PATH)
        return {"message": f"Moved {moved} orphaned files to temp", "moved": moved}


@router.post("/pixiv-upgrades/next")
def scan_next_pixiv_upgrade(request: Request):
    """Check the next unmarked numeric PID and stage a better Pixiv original."""
    require_admin_user_id(request)
    try:
        with PixivUpgradeService.LOCK:
            with get_db_context() as db:
                return PixivUpgradeService.scan_next(db)
    except PixivLookupError as exc:
        # A temporary failure deliberately leaves pixiv_checked_at empty.
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@router.post("/pixiv-upgrades/resolve")
def resolve_pixiv_upgrade(choice: schemas.PixivUpgradeResolveRequest, request: Request):
    """Replace the current original, or keep it, after an administrator preview."""
    require_admin_user_id(request)
    try:
        with PixivUpgradeService.LOCK:
            with get_db_context() as db:
                return PixivUpgradeService.resolve(db, choice.token, choice.action)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.post("/duplicates/scan")
def scan_existing_duplicates(
    request: Request,
    limit: int = Query(25, ge=1, le=100),
    local_validation: bool = Query(False),
    options: schemas.ExistingDuplicateScanRequest | None = None,
):
    """Find existing images that share a character and are visually similar."""
    require_admin_user_id(request)
    with get_db_context() as db:
        result = ImageService.scan_existing_perceptual_duplicates(
            db,
            limit=limit,
            excluded_pairs=options.excluded_pairs if options else None,
        )
        from .. import models
        pending_ids = [image_id for pair in result["groups"] for image_id in pair["image_ids"]]
        if pending_ids:
            db.query(models.Image).filter(models.Image.image_id.in_(pending_ids)).update({"local_checked_at": None}, synchronize_session=False)
        elif local_validation:
            from ..local_check import mark_ready
            deferred = {image_id for pair in (options.excluded_pairs if options else []) for image_id in pair}
            for image in db.query(models.Image).filter_by(file_status="available").all():
                if image.image_id not in deferred: mark_ready(image)
        return result


@router.post("/duplicates/resolve")
def resolve_existing_duplicates(choice: schemas.ExistingDuplicateResolveRequest, request: Request):
    """Remember an intentional pair or merge a true duplicate after revalidation."""
    admin_user_id = require_admin_user_id(request)
    try:
        with ImageService.DUPLICATE_WRITE_LOCK:
            with get_db_context() as db:
                if choice.action == "distinct":
                    ImageService._validate_existing_duplicate_pair(
                        db, choice.image_ids[0], choice.image_ids[1],
                    )
                    ImageService.remember_distinct_duplicate_pair(
                        db, choice.image_ids[0], choice.image_ids[1], decided_by=admin_user_id,
                    )
                    from ..local_check import mark_ready
                    from .. import models
                    for image_id in choice.image_ids: mark_ready(db.get(models.Image, image_id))
                    return {"message": "已标记为两张不同图片，后续不再提示", "action": "distinct", "archived": 0}
                if not choice.keep_image_id:
                    raise ValueError("A kept image is required for merging")
                other_image_id = next(image_id for image_id in choice.image_ids if image_id != choice.keep_image_id)
                ImageService._validate_existing_duplicate_pair(db, choice.keep_image_id, other_image_id)
                ImageService.merge_duplicate_image_metadata(
                    db, choice.keep_image_id, other_image_id, choice.metadata_sources,
                )
                from ..local_check import mark_ready
                from .. import models
                db.flush()
                mark_ready(db.get(models.Image, choice.keep_image_id))
                archived = 1
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return {
        "message": f"已保留 {choice.keep_image_id}，合并信息并删除 {archived} 份重复文件",
        "action": "merge",
        "kept_image_id": choice.keep_image_id,
        "archived": archived,
        "deleted": archived,
    }
