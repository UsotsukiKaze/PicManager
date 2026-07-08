from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from PIL import Image
import os
import tempfile

from ... import schemas
from ...config import settings
from ...database import get_db_context
from ...security.api_key import require_bot_api_key
from ...security.tickets import build_login_url, create_login_ticket
from ...services import CharacterService, EmojiService, EmotionTagService, FeatureTagService, GroupService, ImageService

router = APIRouter(dependencies=[Depends(require_bot_api_key)])


def _public_image_url(file_path: str) -> str:
    public_base = getattr(settings, "PUBLIC_BASE_URL", "").rstrip("/")
    normalized = file_path.lstrip("/")
    return f"{public_base}/{normalized}" if public_base else f"/{normalized}"


def _public_thumb_url(image: dict) -> str:
    public_base = getattr(settings, "PUBLIC_BASE_URL", "").rstrip("/")
    image_id = str(image.get("image_id") or "").strip()
    thumb_path = f"resource/thumbs/{image_id}.webp" if image_id else image.get("file_path", "")
    return f"{public_base}/{thumb_path}" if public_base else f"/{thumb_path}"


def _with_image_url(image: dict) -> dict:
    result = dict(image)
    original_url = _public_image_url(result["file_path"])
    result["original_image_url"] = original_url
    result["thumbnail_url"] = _public_thumb_url(result)
    result["image_url"] = original_url
    return result


def _public_emoji_url(file_path: str) -> str:
    public_base = getattr(settings, "PUBLIC_BASE_URL", "").rstrip("/")
    normalized = file_path.lstrip("/")
    return f"{public_base}/{normalized}" if public_base else f"/{normalized}"


def _with_emoji_url(emoji: dict) -> dict:
    result = dict(emoji)
    result["emoji_url"] = _public_emoji_url(result["file_path"])
    return result


def _normalize_aliases(value) -> list[str]:
    if not value:
        return []
    if isinstance(value, str):
        return [item.strip() for item in value.split(",") if item.strip()]
    return [item.strip() for item in value if isinstance(item, str) and item.strip()]


def _find_character_by_alias(db, name: str):
    characters = CharacterService.get_characters(db, limit=5000)
    for character in characters:
        if character.get("name") == name:
            return character
        if name in _normalize_aliases(character.get("nicknames")):
            return character
    return None


def _find_group_by_alias(db, name: str):
    groups = GroupService.get_groups(db, limit=5000)
    for group in groups:
        if group.get("name") == name:
            return group
        if name in _normalize_aliases(group.get("aliases")):
            return group
    return None


def _find_feature_tag_by_alias(db, name: str):
    tags = FeatureTagService.get_feature_tags(db, limit=5000)
    for tag in tags:
        if tag.get("name") == name:
            return tag
        if name in _normalize_aliases(tag.get("aliases")):
            return tag
    return None


def _find_emotion_by_alias(db, name: str):
    tags = EmotionTagService.get_emotion_tags(db, limit=5000)
    for tag in tags:
        if tag.get("name") == name:
            return tag
        if name in _normalize_aliases(tag.get("aliases")):
            return tag
    return None


def _resolve_name(db, name: str):
    if not name:
        return None

    character = _find_character_by_alias(db, name)
    if character:
        return {"type": "character", "item": character}

    feature_tag = _find_feature_tag_by_alias(db, name)
    if feature_tag:
        return {"type": "feature_tag", "item": feature_tag}

    group = _find_group_by_alias(db, name)
    if group:
        return {"type": "group", "item": group}

    return None


@router.get("/groups")
def get_bot_groups(skip: int = 0, limit: int = 500):
    """Return groups for bot-side caching."""
    with get_db_context() as db:
        return GroupService.get_groups(db, skip, limit)


@router.get("/characters")
def get_bot_characters(group_id: int | None = None, skip: int = 0, limit: int = 5000):
    """Return characters for bot-side caching and alias matching."""
    with get_db_context() as db:
        return CharacterService.get_characters(db, group_id, skip, limit)


@router.get("/feature-tags")
def get_bot_feature_tags(skip: int = 0, limit: int = 5000):
    """Return feature tags for bot-side caching and alias matching."""
    with get_db_context() as db:
        return FeatureTagService.get_feature_tags(db, skip, limit)


@router.get("/emotion-tags")
def get_bot_emotion_tags(skip: int = 0, limit: int = 5000):
    """Return emoji emotion tags for bot-side caching."""
    with get_db_context() as db:
        return EmotionTagService.get_emotion_tags(db, skip, limit)


@router.get("/resolve")
def resolve_bot_target(name: str):
    """Resolve a user-facing name to a character, feature tag, or group."""
    target = name.strip()
    if not target:
        raise HTTPException(status_code=400, detail="Name is required")

    with get_db_context() as db:
        resolved = _resolve_name(db, target)
        if not resolved:
            raise HTTPException(status_code=404, detail="Target not found")
        return resolved


@router.get("/random")
def get_bot_random_image(
    name: str | None = None,
    group_id: int | None = None,
    character_id: int | None = None,
    exclude_group_id: int | None = None,
    feature_tag_id: int | None = None,
):
    """Return a random image using bot-oriented target resolution."""
    resolved = None
    with get_db_context() as db:
        if name and not group_id and not character_id and not feature_tag_id:
            resolved = _resolve_name(db, name.strip())
            if not resolved:
                raise HTTPException(status_code=404, detail="Target not found")
            if resolved["type"] == "character":
                character_id = resolved["item"]["id"]
            elif resolved["type"] == "feature_tag":
                feature_tag_id = resolved["item"]["id"]
            elif resolved["type"] == "group":
                group_id = resolved["item"]["id"]

        image = ImageService.get_random_image(db, group_id, character_id, exclude_group_id, feature_tag_id)
        if not image:
            raise HTTPException(status_code=404, detail="Image not found")

        result = _with_image_url(image)
        if resolved:
            result["matched_type"] = resolved["type"]
            result["matched_name"] = resolved["item"].get("name")
        return result


@router.get("/emojis/random")
def get_bot_random_emoji(
    group_id: int | None = None,
    character_id: int | None = None,
    emotion_id: int | None = None,
):
    """Return a random GIF emoji for bot-side sending."""
    with get_db_context() as db:
        emoji = EmojiService.get_random_emoji(db, group_id, character_id, emotion_id)
        if not emoji:
            raise HTTPException(status_code=404, detail="Emoji not found")
        return _with_emoji_url(emoji)


@router.post("/emojis/upload")
async def upload_bot_emoji(
    file: UploadFile = File(...),
    character_ids: str = Form("[]"),
    group_ids: str = Form("[]"),
    emotion_ids: str = Form("[]"),
    description: str | None = Form(None),
):
    """Upload a referenced QQ GIF emoji into PicManager."""
    import json

    file_extension = (file.filename or "").split(".")[-1].lower()
    if file_extension != "gif":
        raise HTTPException(status_code=400, detail="Only GIF emoji resources are supported")
    try:
        character_id_list = [int(item) for item in json.loads(character_ids or "[]")]
        group_id_list = [int(item) for item in json.loads(group_ids or "[]")]
        emotion_id_list = [int(item) for item in json.loads(emotion_ids or "[]")]
    except (TypeError, ValueError, json.JSONDecodeError) as exc:
        raise HTTPException(status_code=400, detail="Invalid tag ids") from exc

    temp_file_path = ""
    try:
        os.makedirs(settings.TEMP_PATH, exist_ok=True)
        with tempfile.NamedTemporaryFile(delete=False, suffix=".gif", dir=settings.TEMP_PATH) as temp_file:
            temp_file_path = temp_file.name
            total = 0
            while True:
                chunk = await file.read(1024 * 1024)
                if not chunk:
                    break
                total += len(chunk)
                if total > settings.MAX_FILE_SIZE:
                    raise HTTPException(status_code=413, detail="File too large")
                temp_file.write(chunk)
        with Image.open(temp_file_path) as image:
            if (image.format or "").upper() != "GIF":
                raise HTTPException(status_code=400, detail="Only GIF emoji resources are supported")
            if not getattr(image, "is_animated", False):
                raise HTTPException(status_code=400, detail="Static images are not supported")
            image.verify()

        with get_db_context() as db:
            emoji = EmojiService.create_emoji(
                db,
                schemas.EmojiCreate(
                    character_ids=character_id_list,
                    group_ids=group_id_list,
                    emotion_ids=emotion_id_list,
                    description=description,
                ),
                temp_file_path,
                file.filename or "qq-emoji.gif",
                "gif",
            )
            return _with_emoji_url(EmojiService.emoji_to_dict(emoji))
    finally:
        try:
            if temp_file_path and os.path.exists(temp_file_path):
                os.unlink(temp_file_path)
        except OSError:
            pass


@router.post("/tickets", response_model=schemas.BotLoginTicketResponse)
def create_bot_login_ticket(ticket_create: schemas.BotLoginTicketCreate):
    """Issue a one-time QQ login ticket for the bot management plugin."""
    with get_db_context() as db:
        issued = create_login_ticket(
            db,
            qq_number=ticket_create.qq_number,
            purpose=ticket_create.purpose,
            redirect_path=ticket_create.redirect_path,
            created_by=ticket_create.created_by,
        )
        return schemas.BotLoginTicketResponse(
            ticket=issued.ticket,
            login_url=build_login_url(issued.ticket, issued.record.redirect_path),
            expires_at=issued.record.expires_at,
            purpose=issued.record.purpose,
            qq_number=issued.record.qq_number,
        )
