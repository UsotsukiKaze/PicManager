"""Private media cache for the page reader, separate from the import cart."""

import secrets
import threading
import time
from contextlib import contextmanager
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

from PIL import Image

from ...config import settings
from .provider import download, PixivError, trusted_image_url

LOCK = threading.Lock()
FILE_LOCKS = {}
ENCODE_SLOTS = threading.BoundedSemaphore(2)
CACHE_LOCK = threading.Lock()
CACHE_STATES = {}
TYPES = {"JPEG": "image/jpeg", "PNG": "image/png", "WEBP": "image/webp", "GIF": "image/gif", "BMP": "image/bmp"}


def image_type(path):
    with Image.open(path) as image:
        if image.width * image.height > 50_000_000 or image.format not in TYPES:
            raise PixivError("invalid_image")
        kind = TYPES[image.format]
        image.verify()
    return kind


@contextmanager
def file_lock(path):
    with LOCK:
        entry = FILE_LOCKS.setdefault(path, [threading.Lock(), 0])
        entry[1] += 1
    try:
        with entry[0]:
            yield
    finally:
        with LOCK:
            entry[1] -= 1
            if not entry[1]:
                FILE_LOCKS.pop(path, None)


def make_webp(source, target):
    with ENCODE_SLOTS, Image.open(source) as image:
        if getattr(image, "is_animated", False):
            return False
        mode = "RGBA" if "A" in image.getbands() else "RGB"
        image.convert(mode).save(target, format="WEBP", quality=84, method=4)
    return True


@contextmanager
def cache_space(root, path, limit):
    """Account for in-flight files; scan periodically or when near the quota."""
    with CACHE_LOCK:
        state = CACHE_STATES.get(root)
        if state is None:
            if len(CACHE_STATES) >= 64:
                idle = next((key for key, value in CACHE_STATES.items() if not value['reserved']), None)
                if idle is not None:
                    CACHE_STATES.pop(idle)
            state = CACHE_STATES[root] = {'checked': float('-inf'), 'used': 0, 'reserved': 0, 'sizes': {}}
        budget = max(settings.PIXIV_MAX_DOWNLOAD_BYTES, 512 * 1024 * 1024)
        if time.monotonic() - state['checked'] >= 60 or state['used'] + state['reserved'] + limit > budget:
            files = []
            for cached in root.glob('*/*.img'):
                try:
                    stat = cached.stat()
                    files.append((cached, stat.st_size, stat.st_mtime))
                except OSError:
                    continue
            state['sizes'] = {cached: size for cached, size, _ in files}
            state['used'] = sum(state['sizes'].values())
            for cached, size, modified in sorted(files, key=lambda item: item[2]):
                if time.time() - modified <= 86400 and state['used'] + state['reserved'] + limit <= budget:
                    continue
                with LOCK:
                    if cached in FILE_LOCKS:
                        continue
                    try:
                        cached.unlink(missing_ok=True)
                    except OSError:
                        continue
                state['sizes'].pop(cached, None)
                state['used'] -= size
            state['checked'] = time.monotonic()
        state['reserved'] += limit
    try:
        yield
    finally:
        with CACHE_LOCK:
            state['reserved'] -= limit
            try:
                size = path.stat().st_size
            except OSError:
                size = None
            if size is not None:
                state['used'] += size - state['sizes'].get(path, 0)
                state['sizes'][path] = size


def cached_media(url, revision, name, limit, *, webp=False, lane="reader"):
    root = Path(settings.TEMP_PATH) / "pixiv-ol-viewer"
    folder = root / revision
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"{name}.img"
    with file_lock(path):
        if not path.is_file():
            stage = path.with_name(f"{path.stem}-{secrets.token_hex(4)}.part")
            try:
                with cache_space(root, path, limit):
                    download(url, stage, limit=limit, lane=lane)
                    image_type(stage)
                    stage.replace(path)
            finally:
                stage.unlink(missing_ok=True)
        kind = image_type(path)
        if webp and kind != "image/webp":
            stage = path.with_name(f"{path.stem}-{secrets.token_hex(4)}.part")
            try:
                if make_webp(path, stage):
                    kind = image_type(stage)
                    stage.replace(path)
                    with CACHE_LOCK:
                        state = CACHE_STATES.get(root)
                        if state and path in state['sizes']:
                            size = path.stat().st_size
                            state['used'] += size - state['sizes'][path]
                            state['sizes'][path] = size
            finally:
                stage.unlink(missing_ok=True)
        return path, kind


def original(art, revision, page):
    urls = art.get("originals") or []
    if page < 0 or page >= art["page_count"] or page >= len(urls):
        raise PixivError("invalid_page")
    return cached_media(urls[page], revision, f"{art['pid']}_p{page}", settings.PIXIV_MAX_DOWNLOAD_BYTES, lane="original")


def clear_preview_url(art, page):
    if page < 0 or page >= art["page_count"]:
        raise PixivError("invalid_page")
    previews = art.get("page_previews") or []
    url = previews[page] if page < len(previews) else ""
    originals = art.get("originals") or []
    if not url or url in originals:
        url = originals[page] if page < len(originals) else (art.get("preview") if page == 0 else "")
    if not trusted_image_url(url):
        raise PixivError("preview_unavailable")
    parsed = urlsplit(url)
    path = parsed.path
    # Pixiv master previews keep page identity and proportions without crop/thumbnail sizing.
    if "/img-master/" in path:
        path = "/img-master/" + path.split("/img-master/", 1)[1]
    elif "/img-original/" in path:
        path = "/img-master/" + path.split("/img-original/", 1)[1]
        path = path.rsplit(".", 1)[0] + "_master1200.jpg"
    elif url in originals:
        fallback = art.get("preview") if page == 0 else ""
        if not trusted_image_url(fallback) or fallback in originals:
            raise PixivError("preview_unavailable")
        return fallback
    return urlunsplit((parsed.scheme, parsed.netloc, path, parsed.query, ""))


def clear_preview(art, revision, page):
    return cached_media(
        clear_preview_url(art, page), revision, f"{art['pid']}_p{page}-preview", 8 * 1024 * 1024, webp=True
    )


def avatar(art, revision):
    url = art.get("author_avatar")
    if not trusted_image_url(url):
        raise PixivError("preview_unavailable")
    return cached_media(url, revision, f"artist-{art['author_id']}-avatar", 2 * 1024 * 1024, lane="avatar")
