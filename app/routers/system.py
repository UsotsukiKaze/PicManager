from fastapi import APIRouter, Request, Query

from .. import schemas
from ..config import settings
from ..database import get_db_context
from ..security.permissions import require_admin_user_id
from ..services import ImageService, SystemService

router = APIRouter()


@router.get("/status", response_model=schemas.SystemStatus)
def get_system_status():
    """Return public system counters used by the web UI."""
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
