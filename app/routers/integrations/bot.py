from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from PIL import Image
import os
import tempfile
from datetime import datetime
from uuid import uuid4
import hashlib
import hmac
import time

from ... import schemas
from ...config import settings
from ...database import get_db_context
from ...models import AgeAssertionNonce, AgeAuthorizationRequest, GroupAgeSetting, User, UserRole
from ...security.api_key import require_bot_api_key
from ...security.image_tokens import sign_bot_image
from ...security.tickets import build_lan_login_url, build_login_url, create_login_ticket, normalize_qq_number
from ...services import CharacterService, EmojiService, EmotionTagService, FeatureTagService, GroupService, ImageService

router = APIRouter(dependencies=[Depends(require_bot_api_key)])


def _age_superusers() -> set[str]:
    values = {
        item.strip()
        for item in str(getattr(settings, "AGE_RATING_SUPERUSERS", "")).split(",")
        if item.strip()
    }
    values.add(str(settings.ROOT_QQ))
    return values


def _verify_age_assertion(action: str, subject_id: str, subject_role: str, target: str,
                          timestamp: int, nonce: str, signature: str, db=None) -> None:
    secret = str(getattr(settings, "AGE_RATING_ASSERTION_SECRET", ""))
    if not secret:
        raise HTTPException(status_code=503, detail="Age assertion secret is not configured")
    now = int(time.time())
    if abs(now - int(timestamp)) > 120:
        raise HTTPException(status_code=401, detail="Age assertion expired")
    nonce = str(nonce or "").strip()
    if len(nonce) < 16:
        raise HTTPException(status_code=401, detail="Age assertion nonce is invalid")
    message = "|".join((action, str(subject_id), str(subject_role), str(target), str(timestamp), nonce))
    expected = hmac.new(secret.encode(), message.encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected, str(signature or "")):
        raise HTTPException(status_code=401, detail="Age assertion signature is invalid")
    if db is not None:
        if db.query(AgeAssertionNonce).filter(AgeAssertionNonce.nonce == nonce).first():
            raise HTTPException(status_code=401, detail="Age assertion nonce is reused")
        db.add(AgeAssertionNonce(nonce=nonce))
        db.flush()


def _public_resource_url(resource_path: str) -> str:
    public_base = getattr(settings, "PUBLIC_BASE_URL", "").rstrip("/")
    normalized = resource_path.lstrip("/")
    return f"{public_base}/{normalized}" if public_base else f"/{normalized}"


def _public_thumb_url(image: dict) -> str | None:
    image_id = str(image.get("image_id") or "").strip()
    if not image_id:
        return None
    return _public_resource_url(f"resource/thumbs/{image_id}.webp")


def _protected_original_url(image: dict) -> str | None:
    image_id = str(image.get("image_id") or "").strip()
    if not image_id:
        return None
    expires, signature = sign_bot_image(image_id)
    return _public_resource_url(
        f"resource/originals/{image_id}?expires={expires}&signature={signature}"
    )


def _with_image_url(image: dict) -> dict:
    result = dict(image)
    # Never expose the on-disk store path in an integration response. It is
    # neither a valid public URL nor a stable authorization boundary.
    result.pop("file_path", None)
    thumbnail_url = _public_thumb_url(result)
    result["original_image_url"] = _protected_original_url(result)
    result["thumbnail_url"] = thumbnail_url
    result["image_url"] = result["original_image_url"] or thumbnail_url
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


def _all_pages(fetch_page, *, limit: int = 5000) -> list[dict]:
    """Aggregate bounded service pages for the trusted bot API contract."""
    page_size = settings.MAX_PAGE_SIZE
    items = []
    while len(items) < limit:
        page = fetch_page(len(items), min(page_size, limit - len(items)))
        items.extend(page)
        if len(page) < page_size:
            break
    return items


def _find_character_by_alias(db, name: str):
    characters = _all_pages(
        lambda skip, limit: CharacterService.get_characters(db, skip=skip, limit=limit)
    )
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
        characters = _all_pages(
            lambda page_skip, page_limit: CharacterService.get_characters(
                db, group_id, page_skip, page_limit
            ),
            limit=skip + min(max(1, limit), 5000),
        )
        return characters[skip:]


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
    audience: str = "group",
    audience_id: str | None = None,
    requester_id: str | None = None,
    assertion_timestamp: int | None = None,
    assertion_nonce: str | None = None,
    assertion_signature: str | None = None,
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

        requester_is_superuser = False
        if requester_id and str(requester_id) in _age_superusers():
            _verify_age_assertion(
                "random", str(requester_id), "superuser", f"{audience}:{audience_id or ''}",
                int(assertion_timestamp or 0), str(assertion_nonce or ""), str(assertion_signature or ""), db,
            )
            requester_is_superuser = True
        if requester_is_superuser:
            max_age_rating = "r18"
        elif audience == "private":
            max_age_rating = "r12"
        else:
            setting = db.query(GroupAgeSetting).filter(
                GroupAgeSetting.group_id == str(audience_id or "")
            ).first()
            max_age_rating = setting.age_rating if setting else "r12"

        image = ImageService.get_random_image(
            db, group_id, character_id, exclude_group_id, feature_tag_id, max_age_rating
        )
        if not image:
            raise HTTPException(status_code=404, detail="Image not found")

        result = _with_image_url(image)
        if resolved:
            result["matched_type"] = resolved["type"]
            result["matched_name"] = resolved["item"].get("name")
        return result


@router.get("/age-rating")
def get_bot_age_rating(
    audience: str = "group",
    audience_id: str | None = None,
    requester_id: str | None = None,
    assertion_timestamp: int | None = None,
    assertion_nonce: str | None = None,
    assertion_signature: str | None = None,
):
    """Return PicManager's effective ceiling for a bot conversation."""
    if requester_id and str(requester_id) in _age_superusers():
        with get_db_context() as db:
            _verify_age_assertion(
                "rating", str(requester_id), "superuser", f"{audience}:{audience_id or ''}",
                int(assertion_timestamp or 0), str(assertion_nonce or ""), str(assertion_signature or ""), db,
            )
            return {"age_rating": "r18", "source": "superuser"}
    if audience == "private":
        return {"age_rating": "r12", "source": "private_default"}
    with get_db_context() as db:
        setting = db.query(GroupAgeSetting).filter(
            GroupAgeSetting.group_id == str(audience_id or "")
        ).first()
        return {
            "age_rating": setting.age_rating if setting else "r12",
            "source": "group_setting" if setting else "group_default",
        }


@router.put("/groups/{group_id}/age-rating")
def update_bot_group_age_rating(group_id: str, update: schemas.BotAgeRatingUpdate):
    """Set All/R12/R16; R18 can only be granted through authorization approval."""
    rating = str(update.age_rating or "").strip().lower()
    role = str(update.actor_role or "").strip().lower()
    if rating not in {"all", "r12", "r16"}:
        raise HTTPException(status_code=400, detail="R18 requires authorization")
    if role not in {"admin", "owner", "superuser"}:
        raise HTTPException(status_code=403, detail="Group admin permission required")
    with get_db_context() as db:
        _verify_age_assertion(
            "set_rating", str(update.actor_id), role, f"{group_id}:{rating}",
            update.timestamp, update.nonce, update.signature, db,
        )
        setting = db.query(GroupAgeSetting).filter(GroupAgeSetting.group_id == group_id).first()
        if not setting:
            setting = GroupAgeSetting(group_id=group_id)
            db.add(setting)
        setting.age_rating = rating
        setting.updated_by = str(update.actor_id)
        db.flush()
        return {"group_id": group_id, "age_rating": rating}


@router.post("/age-authorizations")
def create_bot_age_authorization(request_data: schemas.BotAgeAuthorizationCreate):
    """Create an R18 request for forwarding; this does not grant access."""
    role = str(request_data.requested_by_role or "").strip().lower()
    if role not in {"admin", "owner", "superuser"}:
        raise HTTPException(status_code=403, detail="Group admin permission required")
    with get_db_context() as db:
        _verify_age_assertion(
            "request_r18", str(request_data.requested_by), role, str(request_data.group_id),
            request_data.timestamp, request_data.nonce, request_data.signature, db,
        )
        pending = db.query(AgeAuthorizationRequest).filter(
            AgeAuthorizationRequest.group_id == str(request_data.group_id),
            AgeAuthorizationRequest.status == "pending",
        ).order_by(AgeAuthorizationRequest.created_at.desc()).first()
        if pending:
            return {"request_id": pending.request_id, "status": pending.status, "reused": True}
        record = AgeAuthorizationRequest(
            request_id=str(uuid4()),
            group_id=str(request_data.group_id),
            requested_by=str(request_data.requested_by),
            requested_by_name=request_data.requested_by_name,
            source_group_name=request_data.source_group_name,
        )
        db.add(record)
        db.flush()
        return {"request_id": record.request_id, "status": record.status, "reused": False}


@router.get("/age-authorizations/{request_id}")
def get_bot_age_authorization(request_id: str):
    with get_db_context() as db:
        record = db.query(AgeAuthorizationRequest).filter(
            AgeAuthorizationRequest.request_id == request_id
        ).first()
        if not record:
            raise HTTPException(status_code=404, detail="Authorization request not found")
        return {
            "request_id": record.request_id,
            "group_id": record.group_id,
            "status": record.status,
            "reviewed_by": record.reviewed_by,
        }


@router.put("/age-authorizations/{request_id}/relay")
def bind_bot_age_authorization_relay(
    request_id: str, relay: schemas.BotAgeAuthorizationResolve
):
    with get_db_context() as db:
        record = db.query(AgeAuthorizationRequest).filter(
            AgeAuthorizationRequest.request_id == request_id,
            AgeAuthorizationRequest.status == "pending",
        ).first()
        if not record:
            raise HTTPException(status_code=404, detail="Pending authorization request not found")
        record.authorization_group_id = str(relay.authorization_group_id)
        record.authorization_message_id = str(relay.message_id)
        db.flush()
        return {"request_id": request_id, "status": record.status}


@router.get("/age-authorizations/relay/{authorization_group_id}/{message_id}")
def resolve_bot_age_authorization_relay(authorization_group_id: str, message_id: str):
    with get_db_context() as db:
        record = db.query(AgeAuthorizationRequest).filter(
            AgeAuthorizationRequest.authorization_group_id == authorization_group_id,
            AgeAuthorizationRequest.authorization_message_id == message_id,
            AgeAuthorizationRequest.status == "pending",
        ).first()
        if not record:
            raise HTTPException(status_code=404, detail="Pending authorization request not found")
        return {"request_id": record.request_id, "group_id": record.group_id, "status": record.status}


@router.post("/age-authorizations/{request_id}/reject")
def reject_bot_age_authorization(
    request_id: str, decision: schemas.BotAgeAuthorizationDecision
):
    """Decline and discard a pending R18 request without persisting the rejection."""
    if str(decision.reviewer_id) not in _age_superusers():
        raise HTTPException(status_code=403, detail="Superuser permission required")
    with get_db_context() as db:
        _verify_age_assertion(
            "reject_r18", str(decision.reviewer_id), "superuser", request_id,
            decision.timestamp, decision.nonce, decision.signature, db,
        )
        record = db.query(AgeAuthorizationRequest).filter(
            AgeAuthorizationRequest.request_id == request_id
        ).first()
        if not record:
            raise HTTPException(status_code=404, detail="Authorization request not found")
        if record.status != "pending":
            raise HTTPException(status_code=409, detail="Authorization request is not pending")
        group_id = record.group_id
        db.delete(record)
        db.flush()
        return {
            "request_id": request_id,
            "group_id": group_id,
            "status": "rejected",
        }


@router.post("/age-authorizations/{request_id}/approve")
def approve_bot_age_authorization(
    request_id: str, decision: schemas.BotAgeAuthorizationDecision
):
    """PicManager validates the asserted Superuser decision and performs the grant."""
    if str(decision.reviewer_id) not in _age_superusers():
        raise HTTPException(status_code=403, detail="Superuser permission required")
    with get_db_context() as db:
        _verify_age_assertion(
            "approve_r18", str(decision.reviewer_id), "superuser", request_id,
            decision.timestamp, decision.nonce, decision.signature, db,
        )
        record = db.query(AgeAuthorizationRequest).filter(
            AgeAuthorizationRequest.request_id == request_id
        ).first()
        if not record:
            raise HTTPException(status_code=404, detail="Authorization request not found")
        if record.status == "approved":
            return {"request_id": record.request_id, "group_id": record.group_id, "status": record.status}
        if record.status != "pending":
            raise HTTPException(status_code=409, detail="Authorization request is not pending")
        setting = db.query(GroupAgeSetting).filter(
            GroupAgeSetting.group_id == record.group_id
        ).first()
        if not setting:
            setting = GroupAgeSetting(group_id=record.group_id)
            db.add(setting)
        setting.age_rating = "r18"
        setting.updated_by = str(decision.reviewer_id)
        record.status = "approved"
        record.reviewed_by = str(decision.reviewer_id)
        record.reviewed_at = datetime.utcnow()
        db.flush()
        return {"request_id": record.request_id, "group_id": record.group_id, "status": record.status}


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
def upload_bot_emoji(
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
                chunk = file.file.read(1024 * 1024)
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
        qq_number = normalize_qq_number(ticket_create.qq_number)
        nickname = (ticket_create.nickname or "").strip()[:100] or None
        avatar_url = (ticket_create.avatar_url or "").strip()[:500] or None
        user = db.query(User).filter(User.qq_number == qq_number).first()
        if user is None:
            user = User(
                qq_number=qq_number,
                role=UserRole.ROOT.value if qq_number == settings.ROOT_QQ else UserRole.USER.value,
                password_hash=None,
                nickname=nickname or f"QQ用户{qq_number[-4:]}",
                avatar_url=avatar_url or f"https://q1.qlogo.cn/g?b=qq&nk={qq_number}&s=640",
            )
            db.add(user)
        else:
            if qq_number == settings.ROOT_QQ:
                user.role = UserRole.ROOT.value
            elif user.role == UserRole.ROOT.value:
                user.role = UserRole.USER.value
            user.password_hash = None
            if nickname:
                user.nickname = nickname
            if avatar_url:
                user.avatar_url = avatar_url

        issued = create_login_ticket(
            db,
            qq_number=qq_number,
            purpose=ticket_create.purpose,
            redirect_path=ticket_create.redirect_path,
            created_by=ticket_create.created_by,
        )
        if issued.record.purpose == "phrolova":
            base_url = settings.PHROLOVA_PUBLIC_BASE_URL.rstrip("/")
            if not base_url:
                raise HTTPException(status_code=503, detail="Phrolova public URL is not configured")
            login_url = f"{base_url}/auth/qq#ticket={issued.ticket}"
            lan_login_url = None
        else:
            login_url = build_login_url(issued.ticket, issued.record.redirect_path)
            lan_login_url = build_lan_login_url(issued.ticket, issued.record.redirect_path)
        return schemas.BotLoginTicketResponse(
            ticket=issued.ticket,
            login_url=login_url,
            lan_login_url=lan_login_url,
            expires_at=issued.record.expires_at,
            purpose=issued.record.purpose,
            qq_number=issued.record.qq_number,
        )
