from fastapi import APIRouter, Depends, HTTPException

from ... import models
from ... import schemas
from ...config import settings
from ...database import get_db_context
from ...security.api_key import require_bot_api_key
from ...security.tickets import build_login_url, create_login_ticket
from ...services import CharacterService, GroupService, ImageService

router = APIRouter(dependencies=[Depends(require_bot_api_key)])


def _public_image_url(file_path: str) -> str:
    public_base = getattr(settings, "PUBLIC_BASE_URL", "").rstrip("/")
    normalized = file_path.lstrip("/")
    return f"{public_base}/{normalized}" if public_base else f"/{normalized}"


def _with_image_url(image: dict) -> dict:
    result = dict(image)
    result["image_url"] = _public_image_url(result["file_path"])
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


def _resolve_name(db, name: str):
    if not name:
        return None

    character = _find_character_by_alias(db, name)
    if character:
        return {"type": "character", "item": character}

    group = db.query(models.Group).filter(models.Group.name == name).first()
    if group:
        return {"type": "group", "item": GroupService.get_group(db, group.id)}

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


@router.get("/resolve")
def resolve_bot_target(name: str):
    """Resolve a user-facing name to a character or group."""
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
):
    """Return a random image using bot-oriented target resolution."""
    resolved = None
    with get_db_context() as db:
        if name and not group_id and not character_id:
            resolved = _resolve_name(db, name.strip())
            if not resolved:
                raise HTTPException(status_code=404, detail="Target not found")
            if resolved["type"] == "character":
                character_id = resolved["item"]["id"]
            elif resolved["type"] == "group":
                group_id = resolved["item"]["id"]

        image = ImageService.get_random_image(db, group_id, character_id, exclude_group_id)
        if not image:
            raise HTTPException(status_code=404, detail="Image not found")

        result = _with_image_url(image)
        if resolved:
            result["matched_type"] = resolved["type"]
            result["matched_name"] = resolved["item"].get("name")
        return result


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
