from io import BytesIO
import math
import os
from pathlib import Path
import uuid

from fastapi import APIRouter, File, HTTPException, Request, UploadFile
from PIL import Image, ImageOps, UnidentifiedImageError

from ...config import settings
from ...database import get_db_context
from ..auth import get_current_session


router = APIRouter()

Image.MAX_IMAGE_PIXELS = 50_000_000


def _two_pass_square_resize(image: Image.Image, target_size: int) -> Image.Image:
    """Center-crop to a square, then use two smooth downsampling passes."""
    image = ImageOps.exif_transpose(image)
    if getattr(image, "is_animated", False):
        image.seek(0)
    image = image.convert("RGBA")

    side = min(image.width, image.height)
    left = (image.width - side) // 2
    top = (image.height - side) // 2
    square = image.crop((left, top, left + side, top + side))

    if side > target_size:
        intermediate = max(target_size + 1, round(math.sqrt(side * target_size)))
        intermediate = min(intermediate, side - 1)
        square = square.resize((intermediate, intermediate), Image.Resampling.LANCZOS)
        square = square.resize((target_size, target_size), Image.Resampling.LANCZOS)
    elif side < target_size:
        square = square.resize((target_size, target_size), Image.Resampling.LANCZOS)

    return square


def _encode_avatar(image: Image.Image, max_bytes: int) -> bytes | None:
    for quality in range(92, 31, -4):
        output = BytesIO()
        image.save(output, format="WEBP", quality=quality, method=6, exact=True)
        payload = output.getvalue()
        if len(payload) <= max_bytes:
            return payload
    return None


def process_avatar_bytes(raw: bytes) -> bytes:
    try:
        with Image.open(BytesIO(raw)) as source:
            avatar = _two_pass_square_resize(source, settings.AVATAR_SIZE)
            for size in (settings.AVATAR_SIZE, 448, 384, 320, 256, 192, 128):
                if avatar.width != size:
                    avatar = _two_pass_square_resize(avatar, size)
                payload = _encode_avatar(avatar, settings.AVATAR_MAX_FILE_SIZE)
                if payload is not None:
                    return payload
            raise HTTPException(status_code=422, detail="头像内容过于复杂，无法压缩到 256 KiB 内")
    except HTTPException:
        raise
    except (UnidentifiedImageError, Image.DecompressionBombError, OSError, ValueError) as exc:
        raise HTTPException(status_code=400, detail="无法识别该图片，请换一张后重试") from exc


async def _read_limited(file: UploadFile) -> bytes:
    chunks = []
    total = 0
    while True:
        chunk = await file.read(1024 * 1024)
        if not chunk:
            break
        total += len(chunk)
        if total > settings.AVATAR_UPLOAD_MAX_FILE_SIZE:
            raise HTTPException(status_code=413, detail="头像原图不能超过 10 MiB")
        chunks.append(chunk)
    if not chunks:
        raise HTTPException(status_code=400, detail="请选择头像图片")
    return b"".join(chunks)


@router.post("/avatars/process")
async def process_avatar(request: Request, file: UploadFile = File(...)):
    with get_db_context() as db:
        if not get_current_session(request, db):
            raise HTTPException(status_code=401, detail="请先登录或进入游客模式")

    payload = process_avatar_bytes(await _read_limited(file))
    with Image.open(BytesIO(payload)) as processed:
        output_width, output_height = processed.size
    avatar_name = f"{uuid.uuid4().hex}.webp"
    avatar_root = Path(settings.AVATAR_PATH).resolve()
    avatar_root.mkdir(parents=True, exist_ok=True)
    avatar_path = (avatar_root / avatar_name).resolve()
    avatar_path.relative_to(avatar_root)

    temporary_path = avatar_path.with_suffix(".tmp")
    try:
        temporary_path.write_bytes(payload)
        os.replace(temporary_path, avatar_path)
    finally:
        if temporary_path.exists():
            temporary_path.unlink()

    return {
        "avatar_url": f"/resource/avatars/{avatar_name}",
        "width": output_width,
        "height": output_height,
        "file_size": len(payload),
    }
