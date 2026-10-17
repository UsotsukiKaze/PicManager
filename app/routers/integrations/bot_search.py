"""Bot-only library and Pixiv search endpoints used by UBot."""

from __future__ import annotations

import re
import tempfile
import threading
from pathlib import Path

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy import func

from ... import models
from ...database import get_db_context
from ...integrations.pixiv_ol import service as pixiv_service
from ...integrations.pixiv_ol.provider import PixivError
from ...integrations.pixiv_ol.recommendations import allowed as pixiv_allowed
from ...integrations.pixiv_ol.viewer import original as pixiv_original
from ...pixiv_metadata import canonical_pid, library_pixiv_image, split_pid
from ...security.api_key import require_bot_api_key
from ...services import ImageService
from ...visual_similarity import ALGORITHM, index_missing_batch, match_cached_preview

router = APIRouter(dependencies=[Depends(require_bot_api_key)])
_index_lock = threading.Lock()
_index_building = False


def _ceiling(db, audience: str, audience_id: str) -> str:
    if audience == "private":
        return "r12"
    if audience != "group" or not audience_id.isdigit():
        raise HTTPException(422, "Invalid audience")
    setting = db.query(models.GroupAgeSetting).filter_by(group_id=audience_id).first()
    return setting.age_rating if setting else "r12"


def _permitted(db, rating: str, audience: str, audience_id: str) -> bool:
    return rating in ImageService.allowed_age_ratings(_ceiling(db, audience, audience_id))


def _local_result(db, image_id: str, audience: str, audience_id: str) -> dict | None:
    from .bot import _with_image_url

    image = ImageService.get_image(db, image_id)
    if not image:
        return None
    if not _permitted(db, image.get("age_rating") or "r12", audience, audience_id):
        raise HTTPException(403, "Image age rating exceeds audience limit")
    if not image.get("pid"):
        metadata = db.query(models.PixivImageMetadata).filter_by(image_id=image_id).first()
        if metadata:
            image["pid"] = canonical_pid(metadata.work_id, metadata.page_index)
        else:
            source = db.query(models.PixivImageSource).filter_by(
                image_id=image_id, provider="pixiv"
            ).first()
            if source:
                image["pid"] = canonical_pid(source.work_id, source.page_index)
    return {"source": "library", **_with_image_url(image)}


def _pixiv_account(db):
    try:
        return pixiv_service.require_account(db)
    except PixivError as exc:
        raise HTTPException(503, f"Pixiv account unavailable: {exc.code}") from None


def _cached_art(db, pid: str):
    account = _pixiv_account(db)
    row = db.query(models.PixivArtwork).filter_by(account_revision=account.revision, pid=pid).first()
    return account, row


def _save_remote(raw: dict, actor_id: int, revision: str) -> None:
    pixiv_service.save_artworks(revision, [raw], "bot_lookup", actor_id)


def _fetch_art(pid: str) -> dict:
    with get_db_context() as db:
        account, row = _cached_art(db, pid)
        if row:
            return dict(row.metadata_json)
        actor_id, revision = account.owner_id, account.revision
    try:
        client = pixiv_service.client_for_job(actor_id, revision)
        try:
            raw = client.call("illust_detail", illust_id=pid).get("illust")
        finally:
            client.close()
        art = pixiv_service.normalize_artwork(raw or {})
        if not art or art["pid"] != pid:
            raise HTTPException(404, "Pixiv artwork not found")
        _save_remote(raw, actor_id, revision)
        return art
    except PixivError as exc:
        raise HTTPException(503, f"Pixiv lookup failed: {exc.code}") from None


def _remote_result(pid: str, page: int, audience: str, audience_id: str) -> dict:
    art = _fetch_art(pid)
    if page >= int(art.get("page_count") or 0):
        raise HTTPException(404, "Pixiv page not found")
    with get_db_context() as db:
        account = _pixiv_account(db)
        if not pixiv_allowed(art, account.preferences):
            raise HTTPException(403, "Pixiv artwork is filtered")
        rating = "r18" if art.get("x_restrict") else "r12"
        if not _permitted(db, rating, audience, audience_id):
            raise HTTPException(403, "Image age rating exceeds audience limit")
    return {
        "source": "pixiv", "pid": f"{pid}_p{page}", "work_id": pid,
        "page": page, "page_count": art["page_count"], "title": art.get("title"),
        "artist": {"id": art.get("author_id"), "name": art.get("author")},
        "age_rating": rating,
    }


@router.get("/pid-search")
def pid_search(
    pid: str, audience: str = "group", audience_id: str = "",
):
    parsed = split_pid(pid)
    if not parsed:
        raise HTTPException(422, "Invalid Pixiv PID")
    work_id, page = parsed
    page = page or 0
    with get_db_context() as db:
        image = library_pixiv_image(db, work_id, page)
        if image:
            found = _local_result(db, image.image_id, audience, audience_id)
            if found:
                return found
    return _remote_result(work_id, page, audience, audience_id)


def _local_artists(db, name: str):
    query = db.query(models.PixivArtist).filter(models.PixivArtist.name.contains(name, autoescape=True))
    artists = query.order_by(models.PixivArtist.name, models.PixivArtist.id).limit(30).all()
    exact = [artist for artist in artists if artist.name.casefold() == name.casefold()]
    return exact or artists


def _artist_image(db, artist_id: str, audience: str, audience_id: str):
    candidates = db.query(models.Image.image_id).join(models.PixivImageMetadata).filter(
        models.PixivImageMetadata.artist_id == artist_id,
        models.Image.file_status == ImageService.AVAILABLE,
        models.Image.age_rating.in_(ImageService.allowed_age_ratings(_ceiling(db, audience, audience_id))),
    ).order_by(func.random()).limit(8).all()
    for (image_id,) in candidates:
        found = _local_result(db, image_id, audience, audience_id)
        if found:
            return found
    return None


def _remote_artist(name: str, artist_id: str | None, audience: str, audience_id: str):
    with get_db_context() as db:
        account = _pixiv_account(db)
        actor_id, revision = account.owner_id, account.revision
    try:
        client = pixiv_service.client_for_job(actor_id, revision)
        try:
            if not artist_id:
                results = client.call("search_user", word=name).get("user_previews") or []
                users = [item.get("user") or {} for item in results[:30]]
                exact = [user for user in users if str(user.get("name") or "").casefold() == name.casefold()]
                if not users:
                    raise HTTPException(404, "Artist not found")
                if not exact or len(exact) > 1:
                    users = exact or users
                    return {"candidates": [{"id": str(user["id"]), "name": user.get("name")}
                                           for user in users[:8]]}
                artist_id = str(exact[0]["id"])
            works = client.call("user_illusts", user_id=int(artist_id), type="illust").get("illusts") or []
        finally:
            client.close()
        for raw in works[:30]:
            art = pixiv_service.normalize_artwork(raw)
            if not art or str(art.get("author_id")) != artist_id:
                continue
            with get_db_context() as db:
                account = _pixiv_account(db)
                if not pixiv_allowed(art, account.preferences):
                    continue
                rating = "r18" if art.get("x_restrict") else "r12"
                if not _permitted(db, rating, audience, audience_id):
                    continue
            _save_remote(raw, actor_id, revision)
            return _remote_result(art["pid"], 0, audience, audience_id)
    except PixivError as exc:
        raise HTTPException(503, f"Pixiv artist search failed: {exc.code}") from None
    raise HTTPException(404, "Artist has no permitted artwork")


@router.get("/artist-search")
def artist_search(name: str = "", uid: str = "", audience: str = "group", audience_id: str = "", local_only: bool = False):
    name = name.strip()[:100]
    uid = uid.strip()
    if uid and not re.fullmatch(r"[0-9]{1,30}", uid):
        raise HTTPException(422, "Invalid Pixiv artist ID")
    if not name and not uid:
        raise HTTPException(422, "Artist name or ID required")
    with get_db_context() as db:
        artists = [db.get(models.PixivArtist, uid)] if uid else _local_artists(db, name)
        artists = [artist for artist in artists if artist]
        if local_only:
            return {"candidates": [
                {"id": artist.id, "name": artist.name}
                for artist in artists if uid or artist.name.casefold() == name.casefold()
            ][:8]}
        if len(artists) > 1 or (artists and not uid and artists[0].name.casefold() != name.casefold()):
            return {"candidates": [{"id": artist.id, "name": artist.name} for artist in artists[:8]]}
        if artists:
            found = _artist_image(db, artists[0].id, audience, audience_id)
            if found:
                return found
    return _remote_artist(name, uid or (artists[0].id if artists else None), audience, audience_id)


@router.get("/pixiv-media/{pid}/{page}")
def pixiv_media(pid: str, page: int, audience: str = "group", audience_id: str = ""):
    if not re.fullmatch(r"[0-9]{1,30}", pid) or not 0 <= page < 1000:
        raise HTTPException(422, "Invalid Pixiv artwork")
    _remote_result(pid, page, audience, audience_id)
    with get_db_context() as db:
        account, row = _cached_art(db, pid)
        if not row:
            raise HTTPException(404, "Pixiv artwork not found")
        art, revision = dict(row.metadata_json), account.revision
    try:
        path, kind = pixiv_original(art, revision, page)
    except PixivError as exc:
        raise HTTPException(503, f"Pixiv image unavailable: {exc.code}") from None
    return FileResponse(path, media_type=kind, headers={"Cache-Control": "private, no-store"})


def _build_full_index():
    global _index_building
    try:
        while True:
            with get_db_context() as db:
                if not index_missing_batch(db, limit=48, include_identified=True)["processed"]:
                    break
    finally:
        with _index_lock:
            _index_building = False


@router.post("/image-match")
async def image_match(
    image: UploadFile = File(...), audience: str = Query("group"), audience_id: str = Query(""),
):
    global _index_building
    with get_db_context() as db:
        pending = db.query(models.Image.image_id).outerjoin(models.ImageVisualFingerprint).filter(
            models.Image.file_status == ImageService.AVAILABLE,
            (models.ImageVisualFingerprint.image_id.is_(None)) |
            (models.ImageVisualFingerprint.algorithm != ALGORITHM),
        ).first()
        if pending:
            with _index_lock:
                if not _index_building:
                    _index_building = True
                    threading.Thread(target=_build_full_index, daemon=True).start()
            raise HTTPException(503, "Library image index is warming; retry shortly")
    payload = await image.read(8 * 1024 * 1024 + 1)
    if not payload or len(payload) > 8 * 1024 * 1024:
        raise HTTPException(413, "Image is empty or too large")
    with tempfile.NamedTemporaryFile(suffix=".img", delete=False) as temporary:
        temporary.write(payload)
        path = Path(temporary.name)
    try:
        with get_db_context() as db:
            matches = match_cached_preview(db, path, include_identified=True)
            if not matches or matches[0]["score"] < 98:
                raise HTTPException(404, "No reliable library match")
            if len(matches) > 1 and matches[0]["score"] - matches[1]["score"] < 2:
                raise HTTPException(404, "Library match is ambiguous")
            found = _local_result(db, matches[0]["image_id"], audience, audience_id)
            if not found:
                raise HTTPException(404, "Library image unavailable")
            return found
    finally:
        path.unlink(missing_ok=True)
