from fastapi import APIRouter, HTTPException, Request, Query

from .. import schemas
from ..config import settings
from ..database import get_db_context
from ..security.permissions import require_admin_user_id
from ..services import ImageService, SystemService

router = APIRouter()


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


@router.post("/duplicates/scan")
def scan_existing_duplicates(
    request: Request,
    limit: int = Query(25, ge=1, le=100),
    options: schemas.ExistingDuplicateScanRequest | None = None,
):
    """Find existing images that share a character and are visually similar."""
    require_admin_user_id(request)
    with get_db_context() as db:
        return ImageService.scan_existing_perceptual_duplicates(
            db,
            limit=limit,
            excluded_pairs=options.excluded_pairs if options else None,
        )


@router.post("/duplicates/resolve")
def resolve_existing_duplicates(choice: schemas.ExistingDuplicateResolveRequest, request: Request):
    """Revalidate a scanned duplicate group and archive all but the selected image."""
    require_admin_user_id(request)
    try:
        with ImageService.DUPLICATE_WRITE_LOCK:
            with get_db_context() as db:
                archived = ImageService.resolve_existing_perceptual_duplicates(
                    db,
                    choice.image_ids,
                    choice.keep_image_id,
                )
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return {
        "message": f"已保留 {choice.keep_image_id}，归档 {archived} 张重复图片",
        "kept_image_id": choice.keep_image_id,
        "archived": archived,
    }
