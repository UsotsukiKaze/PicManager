from fastapi import APIRouter, Request

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


@router.post("/cleanup")
def cleanup_orphaned_records(request: Request):
    """Remove database image records whose files no longer exist."""
    require_admin_user_id(request)
    with get_db_context() as db:
        count = ImageService.cleanup_orphaned_records(db, settings.STORE_PATH)
        return {"message": f"Cleaned up {count} orphaned records", "count": count}


@router.post("/scan-store-orphans")
def scan_store_orphans(request: Request):
    """Move image files that are not referenced by the database back to temp."""
    require_admin_user_id(request)
    with get_db_context() as db:
        moved = ImageService.move_orphaned_files_to_temp(db, settings.STORE_PATH, settings.TEMP_PATH)
        return {"message": f"Moved {moved} orphaned files to temp", "moved": moved}
