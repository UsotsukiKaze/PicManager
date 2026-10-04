"""Per-administrator shopping cart, with verified originals under TEMP_PATH."""

import hashlib
import re
import shutil
from datetime import datetime
from pathlib import Path

from PIL import Image

from ... import models
from ...config import settings
from ...database import get_db_context
from . import service
from .provider import PixivError, download
from .recommendations import allowed


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
    with Image.open(path) as image:
        image.verify()
    with Image.open(path) as image:
        if image.width * image.height > 50_000_000:
            raise PixivError("image_too_large")
        extension = {"JPEG": "jpg", "PNG": "png", "WEBP": "webp", "GIF": "gif", "BMP": "bmp"}.get(image.format)
        if not extension:
            raise PixivError("invalid_image")
        return {
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            "bytes": path.stat().st_size,
            "extension": extension,
            "width": image.width,
            "height": image.height,
        }


def cached_path(item, page):
    info = item.cache.get(str(page))
    path = directory(item.id) / f"{page}.img"
    if not info or not path.is_file():
        raise PixivError("cache_missing")
    if hashlib.sha256(path.read_bytes()).hexdigest() != info["sha256"]:
        raise PixivError("cache_changed")
    return path


def cache_pages(provider, job_id, revision, actor_id, payload):
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
                stage.replace(final)
                with get_db_context() as db:
                    item = require_item(db, cart_id, revision, actor_id)
                    item.cache = {**item.cache, str(page): info}
                    item.metadata_json = art
            finally:
                stage.unlink(missing_ok=True)
        if pages:
            with Image.open(folder / f"{pages[0]}.img") as image:
                image.thumbnail((800, 800))
                image.convert("RGB").save(folder / "preview.webp", format="WEBP", quality=85)
        with get_db_context() as db:
            item = require_item(db, cart_id, revision, actor_id)
            item.status = "ready"
        return {"cart_id": cart_id, "pages": pages}
    finally:
        with get_db_context() as db:
            exists = db.get(models.PixivCartItem, cart_id)
        if not exists:
            cleanup(cart_id)
