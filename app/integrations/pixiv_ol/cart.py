"""Per-administrator shopping cart, with verified originals under TEMP_PATH."""

import hashlib
import re
import secrets
import shutil
from base64 import urlsafe_b64encode
from datetime import datetime
from pathlib import Path

from PIL import Image, ImageOps

from ... import models
from ...config import settings
from ...database import get_db_context
from . import service
from .provider import PixivError, download
from .recommendations import allowed
from .image_limits import open_image


def directory(cart_id):
    if not re.fullmatch(r"[a-f0-9]{32}", cart_id):
        raise PixivError("invalid_cart")
    root = (Path(settings.TEMP_PATH) / "pixiv-ol").resolve()
    path = (root / cart_id).resolve()
    if path.parent != root:
        raise PixivError("invalid_cart")
    return path


def cleanup(cart_id):
    path = directory(cart_id)
    if path.exists():
        shutil.rmtree(path, ignore_errors=True)


def cleanup_orphans():
    root = (Path(settings.TEMP_PATH) / "pixiv-ol").resolve()
    if not root.is_dir():
        return
    with get_db_context() as db:
        live = {row[0] for row in db.query(models.PixivCartItem.id).all()}
    for folder in root.iterdir():
        if re.fullmatch(r"[a-f0-9]{32}", folder.name) and folder.name not in live:
            cleanup(folder.name)


def require_item(db, cart_id, revision, actor_id):
    service.require_account(db, revision)
    service.require_actor(db, actor_id)
    item = db.get(models.PixivCartItem, cart_id)
    if not item or item.account_revision != revision or item.actor_id != actor_id:
        raise PixivError("cart_removed")
    return item


def inspect_image(path):
    with open_image(path) as image:
        image.verify()
    with open_image(path) as image:
        extension = {"JPEG": "jpg", "PNG": "png", "WEBP": "webp", "GIF": "gif", "BMP": "bmp"}.get(image.format)
        if not extension:
            raise PixivError("invalid_image")
        return {
            "sha256": file_digest(path),
            "bytes": path.stat().st_size,
            "extension": extension,
            "width": image.width,
            "height": image.height,
        }


def cached_path(item, page):
    info = item.cache.get(str(page))
    return verified_original(item.id, page, info)


def file_digest(path):
    with path.open("rb") as source:
        return hashlib.file_digest(source, "sha256").hexdigest()


def verified_original(cart_id, page, info):
    path = directory(cart_id) / f"{page}.img"
    if not info or not path.is_file():
        raise PixivError("cache_missing")
    if file_digest(path) != info["sha256"]:
        raise PixivError("cache_changed")
    return path


def derivative_paths(cart_id, page, info):
    folder = directory(cart_id)
    digest = info.get("sha256", "")
    if not re.fullmatch(r"[a-f0-9]{64}", digest):
        raise PixivError("cache_changed")
    key = urlsafe_b64encode(bytes.fromhex(digest)).decode("ascii").rstrip("=")
    return (folder / f"thumb-{page}-{key}.webp", folder / f"reader-{page}-{key}.webp")


def prepare_derivatives(cart_id, page, info, *, verified=False):
    """Generate both library-compatible WebPs from a single local decode."""
    from .viewer import ENCODE_SLOTS, file_lock

    thumb, preview = derivative_paths(cart_id, page, info)
    if thumb.is_file() and preview.is_file():
        return thumb, preview
    original = thumb.parent / f"{page}.img"
    with file_lock(original):
        if thumb.is_file() and preview.is_file():
            return thumb, preview
        if not verified:
            verified_original(cart_id, page, info)
        with ENCODE_SLOTS, open_image(original) as source:
            size = max(settings.PREVIEW_SIZE, settings.THUMBNAIL_SIZE)
            source.draft("RGB", (size, size))
            ImageOps.exif_transpose(source, in_place=True)
            source.thumbnail((size, size), Image.Resampling.LANCZOS)
            image = source if source.mode in ("RGB", "RGBA") else source.convert(
                "RGBA" if "transparency" in source.info else "RGB"
            )
            for target, dimension, quality, method in (
                (preview, settings.PREVIEW_SIZE, settings.PREVIEW_QUALITY, 4),
                (thumb, settings.THUMBNAIL_SIZE, settings.THUMBNAIL_QUALITY, settings.THUMBNAIL_WEBP_METHOD),
            ):
                if target.is_file():
                    continue
                scaled = image.copy() if max(image.size) > dimension else image
                scaled.thumbnail((dimension, dimension), Image.Resampling.LANCZOS)
                stage = target.parent / f"preview-{secrets.token_hex(8)}.part"
                try:
                    scaled.save(stage, "WEBP", quality=quality, method=method)
                    stage.replace(target)
                finally:
                    stage.unlink(missing_ok=True)
    return thumb, preview


def pending_derivatives():
    """Snapshot only ready pages so idle backfill never holds a database session while encoding."""
    with get_db_context() as db:
        rows = db.query(models.PixivCartItem.id, models.PixivCartItem.pages, models.PixivCartItem.cache).filter_by(
            status="ready"
        ).order_by(models.PixivCartItem.created_at.desc()).all()
    for cart_id, pages, cache in rows:
        for page in pages:
            info = cache.get(str(page))
            if not info:
                continue
            try:
                paths = derivative_paths(cart_id, page, info)
            except PixivError:
                continue
            if not all(path.is_file() for path in paths):
                yield cart_id, page, info


def cache_pages(provider, job_id, revision, actor_id, payload):
    from .viewer import file_lock

    cart_id = payload["cart_id"]
    try:
        with get_db_context() as db:
            item = require_item(db, cart_id, revision, actor_id)
            pid, pages = item.pid, list(item.pages)
            item.status = "caching"
        art = service.normalize_artwork(provider.call("illust_detail", illust_id=pid).get("illust") or {})
        if not art or art["pid"] != pid:
            raise PixivError("artwork_unavailable")
        folder = directory(cart_id)
        folder.mkdir(parents=True, exist_ok=True)
        for page in pages:
            with get_db_context() as db:
                item = require_item(db, cart_id, revision, actor_id)
                if not allowed(art, service.require_account(db, revision).preferences):
                    raise PixivError("content_filtered")
                if page < 0 or page >= len(art["originals"]):
                    raise PixivError("invalid_page")
                db.get(models.PixivJob, job_id).locked_at = datetime.utcnow()
                try:
                    cached_path(item, page)
                    continue
                except PixivError:
                    pass
                used = sum(
                    int(info.get("bytes", 0))
                    for row in db.query(models.PixivCartItem).all()
                    for info in row.cache.values()
                )
            remaining = settings.PIXIV_OL_CART_MAX_BYTES - used
            if remaining <= 0:
                raise PixivError("cache_full")
            stage, final = folder / f"{page}.part", folder / f"{page}.img"
            try:
                download(
                    art["originals"][page],
                    stage,
                    limit=min(remaining, settings.MAX_FILE_SIZE, settings.PIXIV_MAX_DOWNLOAD_BYTES),
                )
                info = inspect_image(stage)
                with file_lock(final):
                    stage.replace(final)
                with get_db_context() as db:
                    item = require_item(db, cart_id, revision, actor_id)
                    item.cache = {**item.cache, str(page): info}
                    item.metadata_json = art
                try:
                    prepare_derivatives(cart_id, page, info, verified=True)
                except (OSError, ValueError, PixivError):
                    # A derivative can be retried independently of the verified original.
                    pass
            finally:
                stage.unlink(missing_ok=True)
        with get_db_context() as db:
            item = require_item(db, cart_id, revision, actor_id)
            item.status = "ready"
        return {"cart_id": cart_id, "pages": pages}
    finally:
        with get_db_context() as db:
            exists = db.get(models.PixivCartItem, cart_id)
        if not exists:
            cleanup(cart_id)
