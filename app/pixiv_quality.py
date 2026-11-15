"""Compare the actual corresponding Pixiv original and publish without losing labels."""

import hashlib
import secrets
from datetime import datetime
from pathlib import Path

from PIL import Image

from .config import settings
from .file_operations import FileOperation
from .integrations.pixiv_ol import viewer
from .integrations.pixiv_ol.provider import PixivError
from .services import ImageService
from .storage import get_image_storage


def digest(path):
    with Path(path).open('rb') as source:
        value = hashlib.sha256()
        for chunk in iter(lambda: source.read(1024*1024), b''):
            value.update(chunk)
        return value.hexdigest()


def compare(local, remote, *, threshold=None):
    with Image.open(local) as image:
        width, height = image.size
    with Image.open(remote) as image:
        rw, rh = image.size
        extension = {'JPEG': 'jpg', 'PNG': 'png', 'WEBP': 'webp', 'GIF': 'gif'}.get(image.format)
        if not extension:
            raise PixivError('invalid_image')
    same = digest(local) == digest(remote)
    distance = ImageService.dhash_distance(ImageService.compute_dhash(str(local)), ImageService.compute_dhash(str(remote)))
    matched = distance <= (settings.PIXIV_UPGRADE_DHASH_DISTANCE if threshold is None else threshold)
    # Same dimensions can still be a recompressed copy. Prefer the canonical
    # original in that case, rather than treating file size as image quality.
    replace = matched and not same and rw >= width and rh >= height
    sufficient = matched and (same or replace or width >= rw and height >= rh)
    return dict(matched=matched, replace=replace, sufficient=sufficient, distance=distance,
                width=width, height=height, original_width=rw, original_height=rh,
                extension=extension, sha256=digest(remote))


def assess(local, art, revision, page):
    remote, _ = viewer.original(art, revision, page)
    return compare(local, remote), remote


def replace_file(db, image, source, *, filename=None):
    """Publish to a fresh key; the outer transaction decides cleanup or rollback."""
    with Image.open(source) as opened:
        width, height = opened.size
        extension = {'JPEG': 'jpg', 'PNG': 'png', 'WEBP': 'webp', 'GIF': 'gif'}[opened.format]
    backend = get_image_storage(settings, local_root=settings.STORE_PATH)
    key = f'{image.image_id}-quality-{secrets.token_hex(8)}.{extension}'
    old_locator = image.file_path
    old_path = None if old_locator.startswith('r2://') else ImageService.image_full_path(image)
    operation = FileOperation.prepare(db, 'publish', image_id=image.image_id, key=key, backend=backend)
    operation.published(backend.put_file(source, key))
    FileOperation.prepare(db, 'delete', image_id=image.image_id, locator=old_locator, source=old_path, backend=backend)
    image.file_path = operation.record['locator']
    image.file_extension, image.width, image.height = extension, width, height
    image.file_size = Path(source).stat().st_size
    image.perceptual_hash = ImageService.compute_dhash(str(source))
    image.file_status, image.file_checked_at = 'available', datetime.utcnow()
    image.pixiv_quality_checked_at = None
    if filename:
        image.original_filename = filename
    from .jobs import ImageJobQueue
    for kind, path in [('thumbnail', ImageService.thumb_path(image)), ('preview', ImageService.preview_path(image))]:
        Path(path).unlink(missing_ok=True)
        setattr(image, 'thumb_status' if kind == 'thumbnail' else 'preview_status', 'pending')
        ImageJobQueue.enqueue(db, kind, image_id=image.image_id, dedupe_key=f'{kind}:{image.image_id}')


def ensure(db, image, art, revision, page, *, upgrade=True, assessment=None):
    if assessment is None:
        with ImageService.source_file(image) as local:
            quality, remote = assess(local, art, revision, page)
    else:
        _, remote = assessment
        with ImageService.source_file(image) as local:
            quality = compare(local, remote)
    if not quality['matched']:
        image.pixiv_quality_checked_at = None
        return {**quality, 'completed': False, 'upgraded': False}
    upgraded = quality['replace'] and upgrade
    if upgraded:
        replace_file(db, image, remote, filename=f"{art['pid']}_p{page}.{quality['extension']}")
    completed = quality['sufficient'] and (not quality['replace'] or upgrade)
    # Flush file/PID mutations first, then set the evidence for this final file.
    db.flush()
    image.pixiv_quality_checked_at = datetime.utcnow() if completed else None
    return {**quality, 'completed': completed, 'upgraded': upgraded}


def temp_duplicate_can_auto(stored, source, incoming_pid=None):
    from .temp_pixiv import identify
    from .pixiv_metadata import split_pid
    linked = stored.pixiv_metadata is not None or bool(stored.pixiv_sources)
    return linked or (split_pid(incoming_pid) is None and identify(Path(source)) is None)


def merge_temp_source(db, stored, source):
    """Keep the library record, its identity and labels; select a better file only."""
    with ImageService.source_file(stored) as local:
        quality = compare(local, source, threshold=settings.DUPLICATE_DHASH_DISTANCE)
    if not quality['matched']:
        raise PixivError('duplicate_changed')
    better = (quality['original_width'] >= quality['width'] and quality['original_height'] >= quality['height']
              and quality['original_width'] * quality['original_height'] > quality['width'] * quality['height'])
    if better:
        replace_file(db, stored, source, filename=Path(source).name)
    FileOperation.prepare(db, 'discard', source=source)
    return {'image_id': stored.image_id, 'status': 'success', 'upgraded': better,
            'message': '已保留更清晰的图源，沿用库内 Pixiv 关联和标签' if better else '已保留库内图源并整理重复文件'}
