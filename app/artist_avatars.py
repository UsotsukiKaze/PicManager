"""Persistent library artist avatars, independent of the temporary Pixiv viewer cache."""
import logging
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import secrets

from PIL import Image, ImageOps

from .config import settings

_pool = ThreadPoolExecutor(max_workers=2, thread_name_prefix="artist-avatar")
_pending = set()
_lock = threading.Lock()


def avatar_path(artist_id):
    if not str(artist_id).isascii() or not str(artist_id).isdigit():
        raise ValueError("Invalid artist ID")
    return Path(settings.AVATAR_PATH) / f"pixiv-{artist_id}.webp"


def cache_avatar(art):
    from .integrations.pixiv_ol.provider import download, trusted_image_url
    path = avatar_path(art["author_id"])
    if path.is_file():
        return path
    url = art.get("author_avatar")
    if not trusted_image_url(url):
        return None
    path.parent.mkdir(parents=True, exist_ok=True)
    stage = path.with_name(f"{path.stem}-{secrets.token_hex(8)}.part")
    try:
        download(url, stage, limit=2 * 1024 * 1024, lane="avatar")
        with Image.open(stage) as source:
            if source.width * source.height > 16_000_000:
                raise ValueError("Avatar too large")
            image = ImageOps.exif_transpose(source).convert("RGB")
            image.thumbnail((256, 256))
            image.save(stage, "WEBP", quality=88)
        stage.replace(path)
        return path
    finally:
        stage.unlink(missing_ok=True)


def schedule_avatar(art):
    artist_id = str(art.get("author_id") or "")
    if not artist_id.isascii() or not artist_id.isdigit() or not art.get("author_avatar"):
        return
    with _lock:
        if artist_id in _pending or avatar_path(artist_id).is_file():
            return
        _pending.add(artist_id)

    def work():
        try:
            cache_avatar(art)
        except Exception:
            logging.getLogger(__name__).warning("Artist avatar download failed: %s", artist_id, exc_info=True)
        finally:
            with _lock:
                _pending.discard(artist_id)

    _pool.submit(work)
