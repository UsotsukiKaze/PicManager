from fastapi import APIRouter, File, Form, HTTPException, Query, Request, UploadFile
from fastapi.responses import FileResponse
from pathlib import Path
from typing import Optional
from urllib.parse import quote
import json
import mimetypes
import os
import tempfile

from PIL import Image, UnidentifiedImageError

from ... import models, schemas
from ...config import settings
from ...database import get_db_context
from ...security.permissions import require_admin_user_id
from ...services import EmojiService, EmotionTagService
from ..auth import get_session

router = APIRouter()


def _parse_id_list(value: str | None, field_name: str) -> list[int]:
    if not value:
        return []
    try:
        parsed = json.loads(value) if isinstance(value, str) else value
        if not isinstance(parsed, list):
            parsed = [parsed]
        return list(dict.fromkeys([int(item) for item in parsed]))
    except (TypeError, ValueError, json.JSONDecodeError) as exc:
        raise HTTPException(status_code=400, detail=f"Invalid {field_name} format") from exc


EMOJI_IMAGE_FORMATS = {
    "jpg": "JPEG",
    "jpeg": "JPEG",
    "png": "PNG",
    "webp": "WEBP",
    "gif": "GIF",
    "bmp": "BMP",
}


def _verify_emoji_file(path: str, file_extension: str) -> None:
    expected_format = EMOJI_IMAGE_FORMATS.get(file_extension.lower().lstrip("."))
    if not expected_format:
        raise HTTPException(status_code=400, detail="Unsupported emoji image type")
    try:
        with Image.open(path) as image:
            if (image.format or "").upper() != expected_format:
                raise HTTPException(status_code=400, detail="File extension does not match image content")
            image.verify()
    except HTTPException:
        raise
    except (UnidentifiedImageError, OSError) as exc:
        raise HTTPException(status_code=400, detail="Invalid emoji image content") from exc


def _validate_emoji_tags(db, character_ids: list[int], group_ids: list[int], emotion_ids: list[int]) -> None:
    if len(character_ids) > 1 or len(group_ids) > 1 or len(emotion_ids) > 1:
        raise HTTPException(status_code=400, detail="Emoji supports only one group, one character, and one emotion")
    if character_ids:
        existing = db.query(models.Character).filter(models.Character.id.in_(character_ids)).all()
        if len(existing) != len(character_ids):
            missing = set(character_ids) - {item.id for item in existing}
            raise HTTPException(status_code=400, detail=f"Selected characters do not exist: {missing}")
    if group_ids:
        existing = db.query(models.Group).filter(models.Group.id.in_(group_ids)).all()
        if len(existing) != len(group_ids):
            missing = set(group_ids) - {item.id for item in existing}
            raise HTTPException(status_code=400, detail=f"Selected groups do not exist: {missing}")
    if emotion_ids:
        existing = db.query(models.EmotionTag).filter(models.EmotionTag.id.in_(emotion_ids)).all()
        if len(existing) != len(emotion_ids):
            missing = set(emotion_ids) - {item.id for item in existing}
            raise HTTPException(status_code=400, detail=f"Selected emotions do not exist: {missing}")


@router.get("/emotion-tags/", response_model=list[schemas.EmotionTag])
def list_emotion_tags(
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=settings.MAX_PAGE_SIZE),
):
    with get_db_context() as db:
        return EmotionTagService.get_emotion_tags(db, skip, limit)


@router.post("/emotion-tags/", response_model=schemas.EmotionTag)
def create_emotion_tag(tag: schemas.EmotionTagCreate, request: Request):
    require_admin_user_id(request)
    with get_db_context() as db:
        existing = db.query(models.EmotionTag).filter(models.EmotionTag.name == tag.name).first()
        if existing:
            raise HTTPException(status_code=400, detail="Emotion already exists")
        return EmotionTagService.create_emotion_tag(db, tag)


@router.put("/emotion-tags/{tag_id}", response_model=schemas.EmotionTag)
def update_emotion_tag(tag_id: int, tag_update: schemas.EmotionTagUpdate, request: Request):
    require_admin_user_id(request)
    with get_db_context() as db:
        if tag_update.name:
            existing = db.query(models.EmotionTag).filter(models.EmotionTag.name == tag_update.name, models.EmotionTag.id != tag_id).first()
            if existing:
                raise HTTPException(status_code=400, detail="Emotion already exists")
        updated = EmotionTagService.update_emotion_tag(db, tag_id, tag_update)
        if not updated:
            raise HTTPException(status_code=404, detail="Emotion not found")
        return updated


@router.delete("/emotion-tags/{tag_id}")
def delete_emotion_tag(tag_id: int, request: Request):
    require_admin_user_id(request)
    with get_db_context() as db:
        if not EmotionTagService.delete_emotion_tag(db, tag_id):
            raise HTTPException(status_code=404, detail="Emotion not found")
        return {"message": "Emotion deleted", "status": "success"}


@router.get("/emojis/search", response_model=schemas.EmojiSearchResult)
def search_emojis(
    group_id: Optional[int] = None,
    character_id: Optional[int] = None,
    emotion_id: Optional[int] = None,
    description: Optional[str] = None,
    limit: int = Query(50, ge=1, le=settings.MAX_PAGE_SIZE),
    offset: int = Query(0, ge=0),
):
    with get_db_context() as db:
        params = schemas.EmojiSearchParams(
            group_id=group_id,
            character_id=character_id,
            emotion_id=emotion_id,
            description=description,
            limit=limit,
            offset=offset,
        )
        emojis, total = EmojiService.search_emojis(db, params)
        return schemas.EmojiSearchResult(emojis=emojis, total=total, offset=offset, limit=limit)


@router.get("/emojis/random", response_model=schemas.EmojiWithTags)
def random_emoji(group_id: Optional[int] = None, character_id: Optional[int] = None, emotion_id: Optional[int] = None):
    with get_db_context() as db:
        emoji = EmojiService.get_random_emoji(db, group_id, character_id, emotion_id)
        if not emoji:
            raise HTTPException(status_code=404, detail="Emoji not found")
        return emoji


@router.get("/emojis/{emoji_id}", response_model=schemas.EmojiWithTags)
def get_emoji(emoji_id: str):
    with get_db_context() as db:
        emoji = EmojiService.get_emoji(db, emoji_id)
        if not emoji:
            raise HTTPException(status_code=404, detail="Emoji not found")
        return emoji


@router.post("/emojis/upload", response_model=schemas.UploadImageResponse)
def upload_emoji(
    request: Request,
    file: UploadFile = File(...),
    character_ids: str = Form("[]"),
    group_ids: str = Form("[]"),
    emotion_ids: str = Form("[]"),
    description: Optional[str] = Form(None),
):
    require_admin_user_id(request)
    file_extension = (file.filename or "").split(".")[-1].lower()
    if file_extension not in EMOJI_IMAGE_FORMATS:
        raise HTTPException(status_code=400, detail="Unsupported emoji image type")

    character_id_list = _parse_id_list(character_ids, "character_ids")
    group_id_list = _parse_id_list(group_ids, "group_ids")
    emotion_id_list = _parse_id_list(emotion_ids, "emotion_ids")

    os.makedirs(settings.TEMP_PATH, exist_ok=True)
    temp_path = ""
    try:
        with tempfile.NamedTemporaryFile(delete=False, suffix=f".{file_extension}", dir=settings.TEMP_PATH) as temp_file:
            temp_path = temp_file.name
            total = 0
            while True:
                chunk = file.file.read(1024 * 1024)
                if not chunk:
                    break
                total += len(chunk)
                if total > settings.MAX_FILE_SIZE:
                    raise HTTPException(status_code=413, detail="File too large")
                temp_file.write(chunk)
        _verify_emoji_file(temp_path, file_extension)

        with get_db_context() as db:
            _validate_emoji_tags(db, character_id_list, group_id_list, emotion_id_list)
            emoji = EmojiService.create_emoji(
                db,
                schemas.EmojiCreate(
                    character_ids=character_id_list,
                    group_ids=group_id_list,
                    emotion_ids=emotion_id_list,
                    description=description,
                ),
                temp_path,
                file.filename or f"emoji.{file_extension}",
                file_extension,
            )
            return schemas.UploadImageResponse(image_id=emoji.emoji_id, message="Emoji uploaded successfully")
    finally:
        try:
            if os.path.exists(temp_path):
                os.unlink(temp_path)
        except OSError:
            pass


@router.put("/emojis/{emoji_id}")
def update_emoji(emoji_id: str, emoji_update: schemas.EmojiUpdate, request: Request):
    require_admin_user_id(request)
    with get_db_context() as db:
        _validate_emoji_tags(
            db,
            emoji_update.character_ids or [],
            emoji_update.group_ids or [],
            emoji_update.emotion_ids or [],
        )
        emoji = EmojiService.update_emoji(db, emoji_id, emoji_update)
        if not emoji:
            raise HTTPException(status_code=404, detail="Emoji not found")
        return {"message": "Emoji updated", "status": "success"}


@router.delete("/emojis/{emoji_id}")
def delete_emoji(emoji_id: str, request: Request):
    require_admin_user_id(request)
    with get_db_context() as db:
        if not EmojiService.delete_emoji(db, emoji_id):
            raise HTTPException(status_code=404, detail="Emoji not found")
        return {"message": "Emoji deleted", "status": "success"}


@router.get("/emojis/{emoji_id}/download")
def download_emoji(emoji_id: str, request: Request):
    session_id = request.cookies.get("session_id")
    if not session_id:
        raise HTTPException(status_code=401, detail="Login required")
    with get_db_context() as db:
        if not get_session(db, session_id):
            raise HTTPException(status_code=401, detail="Login required")
        db_emoji = db.query(models.Emoji).filter(models.Emoji.emoji_id == emoji_id, models.Emoji.file_status == EmojiService.AVAILABLE).first()
        if not db_emoji or not EmojiService.emoji_file_exists(db_emoji):
            raise HTTPException(status_code=404, detail="Emoji not found")
        full_path = Path(EmojiService.emoji_full_path(db_emoji)).resolve()
        emoji_root = Path(settings.EMOJI_PATH).resolve()
        try:
            full_path.relative_to(emoji_root)
        except ValueError as exc:
            raise HTTPException(status_code=404, detail="Emoji not found") from exc
        safe_name = Path(db_emoji.original_filename or f"{db_emoji.emoji_id}.{db_emoji.file_extension}").name
        encoded_name = quote(safe_name)
        media_type = mimetypes.guess_type(safe_name)[0] or "application/octet-stream"
        response = FileResponse(full_path, media_type=media_type, filename=safe_name)
        response.headers["Content-Disposition"] = f"attachment; filename*=UTF-8''{encoded_name}"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Cache-Control"] = "private, max-age=3600"
        return response
