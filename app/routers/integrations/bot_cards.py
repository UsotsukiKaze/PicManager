"""Card identities locate library originals; identity never bypasses audience limits."""
import hashlib
import hmac
import io
import re
from urllib.parse import urlsplit, parse_qs, quote

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.responses import FileResponse, Response
from PIL import Image, ImageSequence

from ... import models
from ...artist_avatars import avatar_path, cache_avatar
from ...config import settings
from ...database import get_db_context
from ...security.api_key import require_bot_api_key
from ...services import ImageService
from ... import card_art

router = APIRouter(dependencies=[Depends(require_bot_api_key)])


def wide_help_pool(rows):
    """Prefer panoramas; a sparse library falls back only to its widest landscapes."""
    landscape = sorted((r for r in rows if r.width and r.height and r.width > r.height > 0),
                       key=lambda r: r.width / r.height, reverse=True)
    panoramic = [r for r in landscape if r.width / r.height >= 2.4]
    if panoramic:
        return panoramic[:16]
    if not landscape:
        return []
    return [r for r in landscape if r.width / r.height >= (landscape[0].width / landscape[0].height) * .9][:8]


@router.get('/help-art')
def help_art(audience: str = 'group', audience_id: str = ''):
    import secrets
    from sqlalchemy import Float, cast
    from .bot_search import _permitted
    with get_db_context() as db:
        if not _permitted(db, 'all', audience, audience_id):
            raise HTTPException(403, 'Image age rating exceeds audience limit')
        rows = db.query(models.Image).filter(
            models.Image.file_status == 'available', models.Image.age_rating == 'all',
            models.Image.height >= 304, models.Image.width >= 896,
            models.Image.width > models.Image.height,
        ).order_by((cast(models.Image.width, Float) / models.Image.height).desc()).limit(64).all()
        rows = [row for row in rows if ImageService.image_file_exists(row)]
        pool = wide_help_pool(rows)
        if not pool:
            raise HTTPException(404, 'No landscape help artwork available')
        row = secrets.choice(pool)
        path = ImageService.image_full_path(row)
        preview = ImageService.preview_path(row)
        payload = card_art.existing_preview(path, preview, row.width, row.height)
        media_type = 'image/webp'
        if payload is None:
            payload = card_art.artwork(path)
            media_type = 'image/png'
        return Response(payload, media_type=media_type, headers={
            'Cache-Control': 'private, no-store', 'X-Image-Id': row.image_id,
        })


def card_token(image_id):
    signature = hmac.new(settings.SECRET_KEY.encode(), f"pic-card-v1|{image_id}".encode(), hashlib.sha256).hexdigest()[:32]
    return f"picmanager:card:v1:{image_id}:{signature}"


def card_url(image_id):
    base = (settings.PUBLIC_BASE_URL or 'https://pic.usotsuki-kaze.com').rstrip('/')
    return f"{base}/#/gallery?image={quote(image_id, safe='')}"


def link_image_id(value):
    try:
        url, expected = urlsplit(value), urlsplit(card_url('sample'))
    except ValueError:
        return None
    if (url.scheme, url.netloc, url.path) != (expected.scheme, expected.netloc, expected.path):
        return None
    fragment = urlsplit(url.fragment)
    ids = parse_qs(fragment.query).get('image', [])
    if fragment.path == '/gallery' and len(ids) == 1 and re.fullmatch(r'[A-Za-z0-9_-]{1,64}', ids[0]):
        return ids[0]
    return None


@router.get("/card-info/{image_id}")
def card_info(image_id: str, audience: str = "group", audience_id: str = ""):
    from .bot_search import _local_result
    with get_db_context() as db:
        result = _local_result(db, image_id, audience, audience_id)
        if not result:
            raise HTTPException(404, "Library original unavailable")
        result["card_token"] = card_url(image_id)
        result["card_page_url"] = result["card_token"]
        row = db.query(models.Image).filter_by(image_id=image_id).first()
        try:
            result["card_art_revision"] = card_art.revision(ImageService.image_full_path(row))
            try:
                result["card_preview_revision"] = card_art.revision(ImageService.preview_path(row))
            except OSError:
                pass
        except OSError:
            result["card_art_revision"] = None
        return result


@router.get("/card-art/{image_id}")
def card_art_image(image_id: str, audience: str = "group", audience_id: str = ""):
    # Authorization is checked on every hit, even when artwork is already cached.
    card_info(image_id, audience, audience_id)
    with get_db_context() as db:
        row = db.query(models.Image).filter_by(image_id=image_id).first()
        if not row or not ImageService.image_file_exists(row):
            raise HTTPException(404, "Library original unavailable")
        path = ImageService.image_full_path(row)
        preview, width, height = ImageService.preview_path(row), row.width, row.height
    try:
        payload = card_art.existing_preview(path, preview, width, height)
        if payload is not None:
            return Response(payload, media_type="image/webp", headers={"Cache-Control": "private, no-store"})
        return Response(card_art.artwork(path), media_type="image/png", headers={"Cache-Control": "private, no-store"})
    except (OSError, ValueError):
        raise HTTPException(503, "Card artwork temporarily unavailable") from None


@router.post("/card-original")
async def card_original(image: UploadFile = File(...), audience: str = "group", audience_id: str = ""):
    import zxingcpp
    payload = await image.read(8 * 1024 * 1024 + 1)
    if not payload or len(payload) > 8 * 1024 * 1024:
        raise HTTPException(413, "Card too large")
    try:
        with Image.open(io.BytesIO(payload)) as source:
            if source.width * source.height > 20_000_000:
                raise ValueError("Card too large")
            codes = []
            for index, frame in enumerate(ImageSequence.Iterator(source)):
                if index >= 3:
                    break
                codes.extend(zxingcpp.read_barcodes(frame.convert("RGB")))
    except (OSError, ValueError, Image.DecompressionBombError):
        raise HTTPException(422, "Invalid card image") from None
    identities = set()
    for code in codes:
        linked = link_image_id(code.text)
        if linked:
            identities.add(linked)
            continue
        plain = re.fullmatch(r"picmanager:image:([A-Za-z0-9_-]{1,64})", code.text)
        if plain:
            identities.add(plain[1])
            continue
        match = re.fullmatch(r"picmanager:card:v1:([A-Za-z0-9_-]{1,64}):([0-9a-f]{32})", code.text)
        if match and hmac.compare_digest(card_token(match[1]), code.text):
            identities.add(match[1])
    if len(identities) != 1:
        raise HTTPException(404, "No unique PicManager card identity")
    return card_info(identities.pop(), audience, audience_id)


@router.get("/artist-avatar/{artist_id}")
def artist_avatar(artist_id: str):
    if not re.fullmatch(r"[0-9]{1,30}", artist_id):
        raise HTTPException(422, "Invalid artist ID")
    path = avatar_path(artist_id)
    if not path.is_file():
        with get_db_context() as db:
            row = db.query(models.PixivImageSource).join(models.Image).filter(
                models.PixivImageSource.provider == "pixiv",
                models.PixivImageSource.metadata_json["author_id"].as_string() == artist_id,
            ).first()
            art = dict(row.metadata_json) if row else None
            if not art or not art.get("author_avatar"):
                row = db.query(models.PixivArtwork).filter_by(author_id=artist_id).first()
                art = dict(row.metadata_json) if row else None
        if not art:
            raise HTTPException(404, "Artist avatar metadata unavailable")
        try:
            path = cache_avatar(art)
        except Exception:
            raise HTTPException(503, "Artist avatar download failed") from None
    if not path or not path.is_file():
        raise HTTPException(404, "Artist avatar unavailable")
    return FileResponse(path, media_type="image/webp")


@router.get("/card-render/{image_id}")
def shared_card(image_id: str, audience: str = "group", audience_id: str = "", theme: str = "dark"):
    if theme not in {"light", "dark"}:
        raise HTTPException(422, "Invalid theme")
    from .bot_search import _permitted
    from ...pixiv_metadata import canonical_pid
    with get_db_context() as db:
        row = db.query(models.Image).filter_by(image_id=image_id, file_status="available").first()
        if not row or not ImageService.image_file_exists(row):
            raise HTTPException(404, "Library original unavailable")
        if not _permitted(db, row.age_rating, audience, audience_id):
            raise HTTPException(403, "Image age rating exceeds audience limit")
        meta = row.pixiv_metadata
        artist = meta.artist if meta else None
        character = row.characters[0] if row.characters else None
        info = {"image_id": image_id, "pid": row.pid or (canonical_pid(meta.work_id, meta.page_index) if meta else None),
                "age_rating": row.age_rating, "card_token": card_url(image_id), "card_page_url": card_url(image_id),
                "card_art_revision": card_art.revision(ImageService.image_full_path(row)),
                "artist": {"id": artist.id, "name": artist.name} if artist else None,
                "characters": [{"name": character.name, "avatar_url": character.avatar_url,
                                "group_name": character.group.name if character.group else None}] if character else [],
                "groups": [{"name": g.name} for g in row.groups]}
        try:
            info["card_preview_revision"] = card_art.revision(ImageService.preview_path(row))
        except OSError:
            pass
    from ...card_assets import render
    payload, hit = render(info, theme)
    return Response(payload, media_type="image/jpeg", headers={"Cache-Control": "private, no-store", "X-Card-Cache": "hit" if hit else "miss", "X-Age-Rating": info.get("age_rating") or "r12"})


@router.get("/card-assets-status")
def card_assets_status():
    from ...card_assets import connect
    with connect() as db:
        rows = db.execute("SELECT kind,status,count(*) FROM tasks GROUP BY kind,status").fetchall()
        failed = db.execute("SELECT kind,subject,error FROM tasks WHERE status='failed' LIMIT 20").fetchall()
    return {"tasks": [{"kind": k, "status": s, "count": n} for k,s,n in rows], "failed": failed}
