"""One resumable local validation pipeline. Duplicate merges remain administrator decisions."""
from datetime import datetime
from pathlib import Path
from PIL import Image as PILImage
from . import models
from .config import settings
from .services import ImageService


def mark_ready(image):
    if image and image.file_status=='available' and image.thumb_status=='ready' and image.perceptual_hash and ImageService.image_file_exists(image):
        image.local_checked_at=datetime.utcnow()


def run_batch(db, after_id='', limit=200):
    archived=moved=0
    if not after_id:
        archived=ImageService.cleanup_orphaned_records(db,settings.STORE_PATH,mode='archive')
        moved=ImageService.move_orphaned_files_to_temp(db,settings.STORE_PATH,settings.TEMP_PATH)
    rows=db.query(models.Image).filter(models.Image.image_id>after_id,models.Image.file_status!='archived',models.Image.file_status!='deleted').order_by(models.Image.image_id).limit(limit).all()
    failed=[];ready=0
    for image in rows:
        image.local_checked_at=None
        try:
            path=Path(ImageService.image_full_path(image))
            if not ImageService.image_file_exists(image):
                image.file_status='archived';image.thumb_status='missing';archived+=1;continue
            with PILImage.open(path) as original:
                original.load()
                image.width,image.height=original.size
            changed=not image.file_checked_at or datetime.utcfromtimestamp(path.stat().st_mtime)>image.file_checked_at
            previous=image.perceptual_hash
            image.file_size=path.stat().st_size
            image.file_status='available'
            if changed or not previous:
                image.perceptual_hash=ImageService.compute_dhash(str(path))
            if previous and previous!=image.perceptual_hash:
                image.pixiv_metadata=None
                image.pixiv_sources=[]
                image.pixiv_checked_at=None
            image.file_checked_at=datetime.utcnow()
            if not ImageService.ensure_thumbnail(image):
                failed.append(image.image_id);continue
            db.flush()
            ready+=1
        except (OSError,ValueError,RuntimeError):
            image.local_checked_at=None;image.thumb_status='failed';failed.append(image.image_id)
    db.flush()
    cursor=rows[-1].image_id if rows else after_id
    more=db.query(models.Image).filter(models.Image.image_id>cursor,models.Image.file_status.notin_(['archived','deleted'])).count()
    return {'cursor':cursor,'remaining':more,'processed':len(rows),'ready':ready,'failed':failed,'archived':archived,'orphans_moved':moved}
