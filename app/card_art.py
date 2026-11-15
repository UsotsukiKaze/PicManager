"""Private lossless card-sized artwork cache; originals are never modified."""
import hashlib
from io import BytesIO
from pathlib import Path
import threading

from PIL import Image, ImageOps

from .config import settings

_workers = threading.BoundedSemaphore(2)
_stripes = [threading.Lock() for _ in range(64)]
_files = threading.Lock()
MAX_BYTES = 512 * 1024 * 1024


def existing_preview(source, preview, width, height):
    """Reuse only fresh, decodable previews large enough for the card artwork."""
    try:
        path = Path(preview)
        if not width or not height or path.stat().st_mtime_ns < Path(source).stat().st_mtime_ns:
            return None
        scale = min(1, 896 / width, 1280 / height)
        payload = path.read_bytes()
        with Image.open(BytesIO(payload)) as image:
            if image.width < int(width * scale) or image.height < int(height * scale):
                return None
            if abs(image.width / image.height / (width / height) - 1) > .01:
                return None
            image.load()
        return payload
    except (OSError, ValueError):
        return None


def revision(path):
    path = Path(path)
    stat = path.stat()
    return hashlib.sha256(f'v1|{path.resolve()}|{stat.st_size}|{stat.st_mtime_ns}'.encode()).hexdigest()


def artwork(path):
    key = revision(path)
    root = Path(settings.DATA_PATH) / 'card-art-cache'
    target = root / (key + '.png')
    with _stripes[int(key[:4], 16) % len(_stripes)]:
        with _files:
            if target.is_file():
                payload = target.read_bytes()
                target.touch()
                return payload
        with _workers:
            with Image.open(path) as source:
                if source.width * source.height > 100_000_000:
                    raise ValueError('Image too large')
                art = ImageOps.exif_transpose(source).convert('RGB')
            art.thumbnail((896, 1280), Image.Resampling.LANCZOS)
            output = BytesIO()
            art.save(output, 'PNG', compress_level=1)
            payload = output.getvalue()
        if revision(path) != key:
            raise ValueError('Image changed during rendering')
        with _files:
            root.mkdir(parents=True, exist_ok=True)
            stage = target.with_suffix('.part')
            stage.write_bytes(payload)
            stage.replace(target)
            entries = [(p.stat().st_mtime_ns, p.stat().st_size, p) for p in root.glob('*.png')]
            total = sum(size for _, size, _ in entries)
            for _, size, old in sorted(entries):
                if total <= MAX_BYTES:
                    break
                old.unlink()
                total -= size
        return payload
