"""Private, administrator-only Pixiv-ol endpoints."""

import secrets
import hashlib
import json
from pathlib import Path
from typing import Literal
from urllib.parse import urlparse

from fastapi import APIRouter, Depends, HTTPException, Request, Query
from fastapi.responses import FileResponse, Response
from pydantic import BaseModel, Field, SecretStr, field_validator
from sqlalchemy.exc import IntegrityError
from sqlalchemy import func

from ... import models
from ...config import settings
from ...services import ImageService
from ...database import get_db_context
from ...pixiv_metadata import library_pixiv_pages
from ...security.permissions import require_admin_user_id, require_root_user_id
from ...integrations.pixiv_ol import service
from ...integrations.pixiv_ol.jobs import ACCOUNT_LOCK, enqueue, ACTIVE
from ...integrations.pixiv_ol.provider import PixivError, download
from ...integrations.pixiv_ol.recommendations import TagIndex, allowed, normalize

router = APIRouter(dependencies=[Depends(require_admin_user_id)])


def write_guard(request: Request):
    if request.headers.get("x-pixiv-ol") != "1":
        raise HTTPException(403, "缺少 Pixiv-ol 请求标识")
    origin = request.headers.get("origin")
    if origin:
        expected = {str(request.base_url).rstrip("/")}
        if settings.PUBLIC_BASE_URL:
            parsed = urlparse(settings.PUBLIC_BASE_URL)
            expected.add(f"{parsed.scheme}://{parsed.netloc}")
        if origin not in expected:
            raise HTTPException(403, "请求来源不匹配")


def handle_error(exc):
    raise HTTPException(
        409 if exc.code in ("account_changed", "invalid_tags", "group_required", "idempotency_conflict", "pages_unconfirmed", "invalid_page_draft") else 502,
        detail=exc.code,
    ) from None


def private_media(path, kind, request, revision):
    """Call only after all account, ownership, page and preference checks."""
    stat = path.stat()
    identity = f"{revision}:{path.name}:{stat.st_mtime_ns}:{stat.st_size}"
    etag = '"' + hashlib.sha256(identity.encode()).hexdigest()[:32] + '"'
    headers = {
        "Cache-Control": "private, no-cache, must-revalidate",
        "Cloudflare-CDN-Cache-Control": "no-store",
        "Vary": "Cookie",
        "ETag": etag,
    }
    tags = request.headers.get("if-none-match", "").split(",")
    if any(value.strip().removeprefix('W/') in (etag, '*') for value in tags):
        return Response(status_code=304, headers=headers)
    return FileResponse(path, media_type=kind, headers=headers, stat_result=stat)


class ConnectBody(BaseModel):
    refresh_token: SecretStr


class SyncBody(BaseModel):
    kind: Literal["sync", "following", "recommendations"] = "sync"
    restrict: Literal["public", "private"] = "public"
    mode: Literal["personal", "stock", "discovery", "combined", "native"] = "combined"
    first_page: bool = False


class BrowseBody(BaseModel):
    view: Literal["recommendations", "feed"]
    mode: Literal["personal", "stock", "discovery", "combined", "native"] = "combined"
    seen_pids: list[str] = Field(default_factory=list, max_length=2000)

    @field_validator('seen_pids')
    @classmethod
    def validate_seen_pids(cls, values):
        if any(not value.isascii() or not value.isdigit() or len(value) > 30 for value in values):
            raise ValueError('invalid seen PID')
        return list(dict.fromkeys(values))


class LookupBody(BaseModel):
    pid: str = Field(pattern=r"^[0-9]{1,30}$")


class ImportBody(BaseModel):
    pid: str = Field(pattern=r"^[0-9]{1,30}$")
    pages: list[int] = Field(min_length=1, max_length=100)
    group_ids: list[int] = Field(min_length=1, max_length=30)
    character_ids: list[int] = Field(default_factory=list, max_length=50)
    feature_tag_ids: list[int] = Field(default_factory=list, max_length=100)
    new_tags: list[str] = Field(default_factory=list, max_length=100)
    age_rating: Literal["all", "r12", "r16", "r18"] = "r12"
    idempotency_key: str = Field(min_length=8, max_length=64, pattern=r"^[a-zA-Z0-9_-]+$")


class ResolveBody(BaseModel):
    action: Literal["different", "existing", "merge_existing", "merge_new"]
    image_id: str | None = Field(default=None, max_length=64)
    page: int | None = Field(default=None, ge=0, le=999)
    review_key: str | None = Field(default=None, pattern=r"^[a-f0-9]{32}$")
    metadata_sources: dict[Literal["pid", "description", "age_rating", "groups", "characters", "feature_tags"], Literal["merge", "keep", "other"]] = Field(default_factory=dict)


class GroupPreference(BaseModel):
    enabled: bool = True


class PreferencesBody(BaseModel):
    groups: dict[str, GroupPreference] = Field(default_factory=dict)
    alpha: float = Field(default=0.5, ge=0, le=1)
    include_r18: bool = False
    include_r18g: bool = False
    private_following: bool = False
    ai: Literal["exclude", "include", "only"] = "exclude"
    blocked_authors: list[str] = Field(default_factory=list, max_length=200)
    blocked_tags: list[str] = Field(default_factory=list, max_length=200)


class FeedbackBody(BaseModel):
    pid: str = Field(pattern=r"^[0-9]{1,30}$")
    value: Literal["like", "dislike", "later", "clear"]


class MappingBody(BaseModel):
    tag: str = Field(min_length=1, max_length=255)
    group_context: int = Field(default=0, ge=0)
    target_type: Literal["group", "character", "feature", "ignore"]
    target_id: int | None = None
    replace: bool = False


class MappingBatchBody(BaseModel):
    bindings: list[MappingBody] = Field(min_length=1, max_length=50)


class CartAddBody(BaseModel):
    pid: str = Field(pattern=r"^[0-9]{1,30}$")
    pages: list[int] | None = Field(default=None, min_length=1, max_length=100)
    import_mode: Literal["merged", "split"] = "merged"


class CartTagBody(BaseModel):
    group_ids: list[int] = Field(default_factory=list, max_length=30)
    character_ids: list[int] = Field(default_factory=list, max_length=50)
    feature_tag_ids: list[int] = Field(default_factory=list, max_length=100)
    new_tags: list[str] = Field(default_factory=list, max_length=100)
    age_rating: Literal["all", "r12", "r16", "r18"] = "r12"


class CartDraftBody(CartTagBody):
    pages: list[int] = Field(min_length=1, max_length=100)


class CartImportBody(BaseModel):
    item_ids: list[str] = Field(min_length=1, max_length=100)


class LoginBody(BaseModel):
    mode: Literal["default_browser", "cli", "automatic", "manual"] = "default_browser"


class LoginCodeBody(BaseModel):
    code: SecretStr


@router.post("/account/login", dependencies=[Depends(write_guard)])
def start_login(request: Request, body: LoginBody, actor_id=Depends(require_root_user_id)):
    from ...integrations.pixiv_ol import login, cli_login

    if body.mode == "cli" or (
        body.mode == "default_browser" and login.local_request(request) and cli_login.executable()
    ):
        if not login.local_request(request):
            raise HTTPException(409, "login_cli_local_only")
        return cli_login.start(actor_id)
    automatic = body.mode == "automatic" and login.local_request(request) and bool(login.browser_executable())
    session = login.start(actor_id, automatic)
    session["opened"] = (
        body.mode == "default_browser" and login.local_request(request) and login.open_default_browser(session["url"])
    )
    return session


@router.get("/account/login/pending")
def pending_login(actor_id=Depends(require_root_user_id)):
    from datetime import datetime
    from ...integrations.pixiv_ol import login, cli_login

    with get_db_context() as db:
        row = (
            db.query(models.PixivLoginSession)
            .filter(
                models.PixivLoginSession.actor_id == actor_id,
                models.PixivLoginSession.status.in_(("waiting", "cli", "exchanging")),
            )
            .filter(models.PixivLoginSession.expires_at > datetime.utcnow())
            .order_by(models.PixivLoginSession.expires_at.desc())
            .first()
        )
        session = None
        if row:
            session = login.manual_session(row) if row.status == "waiting" else cli_login.session_json(row)
        return {"session": session}


@router.post("/account/login/{session_id}/open", dependencies=[Depends(write_guard)])
def reopen_login(session_id: str, request: Request, actor_id=Depends(require_root_user_id)):
    from datetime import datetime
    from ...integrations.pixiv_ol import login

    with get_db_context() as db:
        row = db.get(models.PixivLoginSession, session_id)
        if not row or row.actor_id != actor_id:
            raise HTTPException(404, "授权会话不存在")
        if row.status != "waiting" or row.expires_at <= datetime.utcnow():
            raise HTTPException(409, "login_expired")
        session = login.manual_session(row)
    session["opened"] = login.local_request(request) and login.open_default_browser(session["url"])
    return session


@router.get("/account/login/{session_id}")
def login_status(session_id: str, actor_id=Depends(require_root_user_id)):
    from datetime import datetime
    from ...integrations.pixiv_ol import cli_login

    with get_db_context() as db:
        row = db.get(models.PixivLoginSession, session_id)
        if not row or row.actor_id != actor_id:
            raise HTTPException(404, "授权会话不存在")
        if row.expires_at <= datetime.utcnow() and row.status in ("browser", "waiting", "cli"):
            row.status, row.verifier = "expired", ""
        return {"id": row.id, "status": row.status, "error": row.error, "phase": cli_login.phase(row.id)}


@router.post("/account/login/{session_id}/complete", dependencies=[Depends(write_guard)])
def complete_login(session_id: str, body: LoginCodeBody, actor_id=Depends(require_root_user_id)):
    from ...integrations.pixiv_ol import login

    code = login.authorization_input(body.code.get_secret_value())
    if not code:
        raise HTTPException(422, "授权回跳链接或授权码无效")
    return login.complete(session_id, actor_id, code)


@router.delete("/account/login/{session_id}", dependencies=[Depends(write_guard)])
def cancel_login(session_id: str, actor_id=Depends(require_root_user_id)):
    with ACCOUNT_LOCK, get_db_context() as db:
        row = db.get(models.PixivLoginSession, session_id)
        if row and row.actor_id == actor_id and row.status in ("browser", "waiting", "cli", "exchanging"):
            row.status, row.verifier = "cancelled", ""
    return {"cancelled": True}


def cart_json(db, item, index=None):
    art = {
        k: v
        for k, v in item.metadata_json.items()
        if k not in ("preview", "originals", "page_previews", "author_avatar")
    }
    art["reader_preview_url"] = f"/api/pixiv-ol/cart/{item.id}/reader-preview"
    art["author_avatar_url"] = f"/api/pixiv-ol/artworks/{item.pid}/avatar"
    art["liked"] = bool(
        db.query(models.PixivFeedback)
        .filter_by(account_revision=item.account_revision, actor_id=item.actor_id, pid=item.pid, value="like")
        .first()
    )
    job = (
        db.get(models.PixivJob, item.import_job_id or item.cache_job_id)
        if (item.import_job_id or item.cache_job_id)
        else None
    )
    return {
        "id": item.id,
        "artwork": {**art, "match": (index or TagIndex(db)).match(art["tags"])},
        "pages": item.pages,
        "draft": item.draft,
        "status": item.status,
        "cached_pages": sorted(int(page) for page in item.cache),
        "bytes": sum(info.get("bytes", 0) for info in item.cache.values()),
        "preview_url": f"/api/pixiv-ol/cart/{item.id}/preview" if item.cache else f"/api/pixiv-ol/previews/{item.pid}",
        "job": job_json(job) if job else None,
    }


@router.get("/cart")
def cart_list(actor_id=Depends(require_admin_user_id)):
    return cart_contents(actor_id)


@router.post("/cart/refresh-tags", dependencies=[Depends(write_guard)])
def cart_refresh_tags(actor_id=Depends(require_admin_user_id)):
    return cart_contents(actor_id, refresh=True)


def cart_contents(actor_id, *, refresh=False):
    with get_db_context() as db:
        account = db.get(models.PixivAccount, 1)
        if not account:
            return {"items": [], "total": 0}
        items = (
            db.query(models.PixivCartItem)
            .filter_by(account_revision=account.revision, actor_id=actor_id)
            .order_by(models.PixivCartItem.created_at.desc())
            .all()
        )
        items = [item for item in items if allowed(item.metadata_json, account.preferences)]
        index = TagIndex(db)
        if refresh:
            from ...integrations.pixiv_ol.cart_tags import refresh_item
            for item in items:
                refresh_item(index, item)
        return {"items": [cart_json(db, item, index) for item in items], "total": len(items)}


@router.post("/cart", status_code=202, dependencies=[Depends(write_guard)])
def cart_add(body: CartAddBody, actor_id=Depends(require_admin_user_id)):
    try:
        with get_db_context() as db:
            account = service.require_account(db)
            item = (
                db.query(models.PixivCartItem)
                .filter_by(account_revision=account.revision, actor_id=actor_id, pid=body.pid)
                .first()
            )
            if item:
                mark_liked(db, account.revision, actor_id, body.pid)
                return cart_json(db, item)
            if (
                db.query(models.PixivCartItem).filter_by(account_revision=account.revision, actor_id=actor_id).count()
                >= 200
            ):
                raise HTTPException(409, "优选夹最多暂存 200 个作品")
            row = db.query(models.PixivArtwork).filter_by(account_revision=account.revision, pid=body.pid).first()
            if not row or not allowed(row.metadata_json, account.preferences):
                raise HTTPException(404, "作品不可用")
            imported = library_pixiv_pages(db, [body.pid]).get(body.pid, set())
            pages = sorted(
                set(body.pages if body.pages is not None else range(min(row.metadata_json["page_count"], 100)))
                - imported
            )
            if not pages or any(page < 0 or page >= row.metadata_json["page_count"] for page in pages):
                raise HTTPException(409, "没有可暂存的投稿页")
            match = TagIndex(db).match(row.metadata_json["tags"])
            draft = {
                "pages": pages,
                "group_ids": match["group_ids"],
                "character_ids": match["character_ids"],
                "feature_tag_ids": match["feature_tag_ids"],
                "new_tags": [],
                "age_rating": "r18" if row.metadata_json["x_restrict"] else "r12",
                "import_mode": body.import_mode,
            }
            from ...integrations.pixiv_ol.cart_tags import initial_state
            draft["_tag_refresh"] = initial_state(draft)
            if body.import_mode == "split":
                tags = {key: value for key, value in draft.items() if key not in ("pages", "import_mode")}
                draft["page_drafts"] = {str(page): dict(tags) for page in pages}
                draft["confirmed_pages"] = []
            item = models.PixivCartItem(
                id=secrets.token_hex(16),
                account_revision=account.revision,
                actor_id=actor_id,
                pid=body.pid,
                pages=pages,
                metadata_json=row.metadata_json,
                draft=draft,
            )
            db.add(item)
            db.flush()
            job = enqueue(db, actor_id, "cache", {"cart_id": item.id}, f"cart:{item.id}")
            item.cache_job_id = job.id
            mark_liked(db, account.revision, actor_id, body.pid)
            return cart_json(db, item)
    except PixivError as exc:
        handle_error(exc)
    except IntegrityError:
        raise HTTPException(409, "作品正在加入，请重试") from None


@router.put("/cart/{cart_id}", dependencies=[Depends(write_guard)])
def cart_update(cart_id: str, body: CartDraftBody, actor_id=Depends(require_admin_user_id)):
    from ...integrations.pixiv_ol.cart import require_item

    with get_db_context() as db:
        account = service.require_account(db)
        item = require_item(db, cart_id, account.revision, actor_id)
        if item.status == "importing":
            raise HTTPException(409, "入库进行中，暂不能编辑")
        if item.draft.get("import_mode") == "split":
            raise HTTPException(409, "分 P 作品请逐页确认标签")
        if not set(body.pages).issubset(item.pages):
            raise HTTPException(422, "只能选择已加入暂存的页")
        draft = body.model_dump()
        draft["import_mode"] = "merged"
        draft["pages"] = sorted(set(body.pages))
        draft["new_tags"] = list({normalize(tag): tag.strip() for tag in body.new_tags if tag.strip()}.values())
        if any(len(tag) > 255 for tag in draft["new_tags"]):
            raise HTTPException(422, "标签过长")
        if draft["group_ids"]:
            from ...integrations.pixiv_ol.jobs import validate_draft

            validate_draft(db, {**draft, "actor_id": actor_id})
        else:
            for ids, cls in ((draft["character_ids"], models.Character), (draft["feature_tag_ids"], models.FeatureTag)):
                if ids and db.query(cls).filter(cls.id.in_(set(ids))).count() != len(set(ids)):
                    raise HTTPException(422, "标签不存在")
        from ...integrations.pixiv_ol.cart_tags import contextual_match, remember_edit
        index = TagIndex(db)
        item.draft = remember_edit(item.draft, draft, contextual_match(index, item.metadata_json.get("tags", []), draft))
        return cart_json(db, item, index)


@router.put("/cart/{cart_id}/pages/{page}", dependencies=[Depends(write_guard)])
def cart_page_update(cart_id: str, page: int, body: CartTagBody, actor_id=Depends(require_admin_user_id)):
    from ...integrations.pixiv_ol.cart import require_item
    from ...integrations.pixiv_ol.jobs import validate_draft

    try:
        with get_db_context() as db:
            account = service.require_account(db)
            item = require_item(db, cart_id, account.revision, actor_id)
            if item.status == "importing":
                raise HTTPException(409, "入库进行中，暂不能编辑")
            if item.draft.get("import_mode") != "split" or page not in item.draft["pages"]:
                raise HTTPException(422, "该页不属于分 P 草稿")
            tags = body.model_dump()
            tags["new_tags"] = list({normalize(tag): tag.strip() for tag in tags["new_tags"] if tag.strip()}.values())
            if any(len(tag) > 255 for tag in tags["new_tags"]):
                raise HTTPException(422, "标签过长")
            validate_draft(db, {**tags, "actor_id": actor_id})
            from ...integrations.pixiv_ol.cart_tags import contextual_match, remember_edit
            previous = item.draft.get("page_drafts", {}).get(str(page), {})
            index = TagIndex(db)
            tags = remember_edit(previous, tags, contextual_match(index, item.metadata_json.get("tags", []), tags))
            item.draft = {
                **item.draft,
                "page_drafts": {**item.draft.get("page_drafts", {}), str(page): tags},
                "confirmed_pages": sorted(set(item.draft.get("confirmed_pages", [])) | {page}),
            }
            return cart_json(db, item)
    except PixivError as exc:
        handle_error(exc)


@router.delete("/cart/{cart_id}", dependencies=[Depends(write_guard)])
def cart_remove(cart_id: str, actor_id=Depends(require_admin_user_id)):
    from ...integrations.pixiv_ol.cart import require_item, cleanup

    with get_db_context() as db:
        account = service.require_account(db)
        item = require_item(db, cart_id, account.revision, actor_id)
        if item.status == "importing":
            raise HTTPException(409, "请等待入库任务结束后移除")
        job = db.get(models.PixivJob, item.cache_job_id) if item.cache_job_id else None
        if job and job.status in ACTIVE:
            job.status, job.dedupe_key = "cancelled", None
        pid = item.pid
        liked = bool(
            db.query(models.PixivFeedback)
            .filter_by(account_revision=account.revision, actor_id=actor_id, pid=pid, value="like")
            .first()
        )
        db.delete(item)
    cleanup(cart_id)
    return {"removed": True, "pid": pid, "liked": liked}


@router.post("/cart/imports", status_code=202, dependencies=[Depends(write_guard)])
def cart_import(body: CartImportBody, actor_id=Depends(require_admin_user_id)):
    from ...integrations.pixiv_ol.cart import require_item, cached_path
    from ...integrations.pixiv_ol.jobs import validate_import_draft

    with get_db_context() as db:
        account = service.require_account(db)
        items = [require_item(db, id_, account.revision, actor_id) for id_ in dict.fromkeys(body.item_ids)]
        for item in items:
            if item.status not in ("ready", "importing") or not allowed(item.metadata_json, account.preferences):
                raise HTTPException(409, "请等待原图缓存完成")
            try:
                validate_import_draft(db, {**item.draft, "actor_id": actor_id})
            except PixivError as exc:
                handle_error(exc)
            for page in item.draft["pages"]:
                cached_path(item, page)
        jobs = []
        for item in items:
            job = db.get(models.PixivJob, item.import_job_id) if item.import_job_id else None
            payload = {**item.draft, "pid": item.pid, "cart_id": item.id}
            if job and {key: value for key, value in job.payload.items() if key != "decisions"} != payload:
                job = None
            if not job:
                digest = hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()[:24]
                job = enqueue(db, actor_id, "import", payload, f"cart:{item.id}:{digest}")
            if job.status == "failed":
                from datetime import datetime

                job.status, job.error, job.attempts, job.available_at = "queued", None, 0, datetime.utcnow()
            item.status, item.import_job_id = "importing", job.id
            jobs.append(job_json(job))
        return {"jobs": jobs}


@router.get("/cart/{cart_id}/preview")
def cart_preview(cart_id: str, page: int | None = Query(None, ge=0, le=999), actor_id=Depends(require_admin_user_id)):
    from ...integrations.pixiv_ol.cart import require_item, directory, cached_path

    with get_db_context() as db:
        account = service.require_account(db)
        item = require_item(db, cart_id, account.revision, actor_id)
        if not allowed(item.metadata_json, account.preferences):
            raise HTTPException(404, "预览不可用")
        if page is not None and page not in item.pages:
            raise HTTPException(404, "该页未加入暂存")
        path = directory(cart_id) / ("preview.webp" if page is None else f"preview-{page}.webp")
        if page is not None and not path.is_file():
            from PIL import Image as PILImage

            try:
                original = cached_path(item, page)
            except PixivError:
                raise HTTPException(404, "预览准备中") from None
            stage = path.with_name(f"preview-{page}-{secrets.token_hex(4)}.part")
            try:
                with PILImage.open(original) as image:
                    image.thumbnail((400, 400))
                    image.convert("RGB").save(stage, format="WEBP", quality=80)
                stage.replace(path)
            finally:
                stage.unlink(missing_ok=True)
    if not path.is_file():
        raise HTTPException(404, "预览准备中")
    return FileResponse(path, media_type="image/webp", headers={"Cache-Control": "private, no-store"})


@router.get("/account")
def account_status():
    with get_db_context() as db:
        account = db.get(models.PixivAccount, 1)
        return {
            "connected": bool(account),
            "name": account.name if account else None,
            "user_id": account.user_id if account else None,
            "status": account.status if account else "disconnected",
            "avatar_url": "/api/pixiv-ol/account/avatar" if account else None,
            "media_revision": account.revision if account else None,
            "sync_state": {k: v for k, v in account.sync_state.items() if k != "account_profile"} if account else {},
        }


@router.get("/account/avatar")
def account_avatar(request: Request, actor_id=Depends(require_admin_user_id)):
    from datetime import datetime
    from ...integrations.pixiv_ol.viewer import avatar

    try:
        with get_db_context() as db:
            account = service.require_account(db)
            revision, user_id = account.revision, account.user_id
            profile = dict(account.sync_state.get("account_profile") or {})
        if not profile.get("avatar"):
            with ACCOUNT_LOCK:
                with get_db_context() as db:
                    account = service.require_account(db, revision)
                    profile = dict(account.sync_state.get("account_profile") or {})
                if not profile.get("avatar"):
                    client = service.client_for_job(actor_id, revision)
                    try:
                        user = client.call("user_detail", user_id=user_id).get("user") or {}
                    finally:
                        client.close()
                    if str(user.get("id")) != user_id:
                        raise PixivError("preview_unavailable")
                    profile = {
                        "avatar": (user.get("profile_image_urls") or {}).get("medium", ""),
                        "fetched_at": datetime.utcnow().isoformat(),
                    }
                    with get_db_context() as db:
                        account = service.require_account(db, revision)
                        account.sync_state = {**account.sync_state, "account_profile": profile}
        path, kind = avatar({"author_id": user_id, "author_avatar": profile.get("avatar")}, revision)
        with get_db_context() as db:
            service.require_account(db, revision)
    except PixivError as exc:
        handle_error(exc)
    return private_media(path, kind, request, revision)


@router.post("/account/connect", dependencies=[Depends(write_guard)])
def connect_account(body: ConnectBody, actor_id=Depends(require_root_user_id)):
    token = body.refresh_token.get_secret_value().strip()
    if not 20 <= len(token) <= 4096:
        raise HTTPException(422, "Refresh Token 长度无效")
    try:
        with ACCOUNT_LOCK:
            return service.connect(token, actor_id)
    except PixivError as exc:
        handle_error(exc)


@router.delete("/account", dependencies=[Depends(write_guard), Depends(require_root_user_id)])
def disconnect_account():
    with ACCOUNT_LOCK, get_db_context() as db:
        cart_ids = [row[0] for row in db.query(models.PixivCartItem.id).all()]
        db.query(models.PixivCartItem).delete()
        db.query(models.PixivLoginSession).filter(
            models.PixivLoginSession.status.in_(("waiting", "browser", "exchanging"))
        ).update({"status": "cancelled", "verifier": ""})
        db.query(models.PixivJob).filter(models.PixivJob.status.in_(ACTIVE)).update(
            {"status": "cancelled", "dedupe_key": None}
        )
        for cls in (models.PixivArtwork, models.PixivFollow, models.PixivRecommendationBatch, models.PixivFeedback):
            db.query(cls).delete()
        db.query(models.PixivAccount).delete()
    from ...integrations.pixiv_ol.cart import cleanup

    for cart_id in cart_ids:
        cleanup(cart_id)
    return {"connected": False}


def job_json(job):
    return {
        "id": job.id,
        "kind": job.kind,
        "status": job.status,
        "result": job.result or {},
        "error": job.error,
        "pid": job.payload.get("pid") if job.kind == "import" else None,
        "page_count": len(job.payload.get("pages", [])) if job.kind == "import" else None,
        "created_at": job.created_at.isoformat() + "Z",
    }


@router.post("/sync", status_code=202, dependencies=[Depends(write_guard)])
def sync(body: SyncBody, actor_id=Depends(require_admin_user_id)):
    try:
        with get_db_context() as db:
            account = service.require_account(db)
            if body.restrict == "private" and not account.preferences.get("private_following"):
                raise HTTPException(403, "Root 尚未启用私密关注同步")
            job = enqueue(db, actor_id, body.kind, body.model_dump(), f"manual:{body.restrict}:{body.mode}")
            return job_json(job)
    except PixivError as exc:
        handle_error(exc)
    except IntegrityError:
        raise HTTPException(409, "任务正在创建，请重试") from None


@router.get("/jobs")
def jobs():
    with get_db_context() as db:
        account = db.get(models.PixivAccount, 1)
        if not account:
            return []
        return [
            job_json(x)
            for x in db.query(models.PixivJob)
            .filter_by(account_revision=account.revision)
            .filter(models.PixivJob.kind != 'stock_refill')
            .order_by(models.PixivJob.id.desc())
            .limit(50)
            .all()
        ]


@router.post("/browse", status_code=202, dependencies=[Depends(write_guard)])
def browse(body: BrowseBody, actor_id=Depends(require_admin_user_id)):
    try:
        with get_db_context() as db:
            payload = body.model_dump()
            if body.view == "feed":
                payload["mode"] = "combined"
            job = enqueue(db, actor_id, f"browse_{body.view}", payload)
            return job_json(job)
    except PixivError as exc:
        handle_error(exc)


@router.post("/jobs/{job_id}/retry", status_code=202, dependencies=[Depends(write_guard)])
def retry(job_id: int, actor_id=Depends(require_admin_user_id)):
    with get_db_context() as db:
        account = service.require_account(db)
        job = db.get(models.PixivJob, job_id)
        if not job or job.account_revision != account.revision:
            raise HTTPException(404, "任务不存在")
        if job.status not in ("failed", "partial"):
            raise HTTPException(409, "任务不可重试")
        job.actor_id, job.status, job.attempts, job.error = actor_id, "queued", 0, None
        from datetime import datetime

        job.available_at = datetime.utcnow()
        return job_json(job)


@router.get("/following")
def following(offset: int = Query(0, ge=0), limit: int = Query(50, ge=1, le=100)):
    with get_db_context() as db:
        account = db.get(models.PixivAccount, 1)
        if not account:
            return {"items": [], "total": 0}
        query = db.query(models.PixivFollow).filter_by(account_revision=account.revision)
        return {
            "total": query.count(),
            "items": [
                {"id": x.author_id, "name": x.name, "restrict": x.restrict}
                for x in query.order_by(models.PixivFollow.id).offset(offset).limit(limit).all()
            ],
        }


@router.get("/library-status")
def library_status(pid: list[str] = Query(default=[], max_length=100)):
    if any(not value.isascii() or not value.isdigit() or len(value) > 30 for value in pid):
        raise HTTPException(422, "无效的 Pixiv PID")
    with get_db_context() as db:
        pages = library_pixiv_pages(db, pid)
        return {"items": [{"pid": value, "imported_pages": sorted(pages.get(value, []))} for value in dict.fromkeys(pid)]}


def public_art(db, row, index=None, actor_id=None, library=None):
    art = row.metadata_json
    # Do not expose remote preview URLs as unauthenticated image resources.
    item = {k: v for k, v in art.items() if k not in ("preview", "originals", "page_previews", "author_avatar")}
    item["preview_url"] = f"/api/pixiv-ol/previews/{row.pid}"
    item["original_url"] = f"/api/pixiv-ol/artworks/{row.pid}/original"
    item["reader_preview_url"] = f"/api/pixiv-ol/artworks/{row.pid}/reader-preview"
    item["author_avatar_url"] = f"/api/pixiv-ol/artworks/{row.pid}/avatar"
    item["liked"] = bool(
        actor_id
        and db.query(models.PixivFeedback)
        .filter_by(account_revision=row.account_revision, actor_id=actor_id, pid=row.pid, value="like")
        .first()
    )
    item["match"] = (index or TagIndex(db)).match(art["tags"])
    library = library_pixiv_pages(db, [row.pid]) if library is None else library
    item["imported_pages"] = sorted(page for page in library.get(row.pid, []) if page < art["page_count"])
    return item


@router.get("/feed")
def feed(
    offset: int = Query(0, ge=0),
    limit: int = Query(20, ge=1, le=50),
    source: Literal["feed", "all"] = "feed",
    cursor: str | None = Query(None, max_length=100),
    actor_id=Depends(require_admin_user_id),
):
    with get_db_context() as db:
        account = db.get(models.PixivAccount, 1)
        if not account:
            return {"items": [], "total": 0}
        index = TagIndex(db)
        query = db.query(models.PixivArtwork).filter_by(account_revision=account.revision)
        if cursor:
            from datetime import datetime
            from sqlalchemy import or_, and_

            try:
                stamp, last_pid = cursor.split("|", 1)
                before = datetime.fromisoformat(stamp)
                if before.tzinfo or not last_pid.isascii() or not last_pid.isdigit():
                    raise ValueError()
            except (ValueError, TypeError):
                raise HTTPException(422, "无效的关注游标") from None
            query = query.filter(
                or_(
                    models.PixivArtwork.published_at < before,
                    and_(models.PixivArtwork.published_at == before, models.PixivArtwork.pid < last_pid),
                )
            )
        rows = query.order_by(models.PixivArtwork.published_at.desc(), models.PixivArtwork.pid.desc()).limit(2000).all()
        rows = [
            x
            for x in rows
            if allowed(x.metadata_json, account.preferences)
            and (source == "all" or any(o["source"].startswith("feed_") for o in x.origins))
        ]
        selected = rows[offset : offset + limit]
        library = library_pixiv_pages(db, [row.pid for row in selected])
        return {
            "items": [public_art(db, x, index, actor_id, library) for x in selected],
            "total": len(rows),
            "next_cursor": (
                f"{selected[-1].published_at.isoformat()}|{selected[-1].pid}"
                if selected and len(rows) > offset + limit
                else None
            ),
            "tail_cursor": f"{selected[-1].published_at.isoformat()}|{selected[-1].pid}" if selected else cursor,
        }


@router.get("/artworks/{pid}")
def artwork(pid: str, actor_id=Depends(require_admin_user_id)):
    with get_db_context() as db:
        account = service.require_account(db)
        row = db.query(models.PixivArtwork).filter_by(account_revision=account.revision, pid=pid).first()
        if not row or not allowed(row.metadata_json, account.preferences):
            raise HTTPException(404, "作品不可用")
        return public_art(db, row, actor_id=actor_id)


@router.post("/lookup", dependencies=[Depends(write_guard)])
def lookup(body: LookupBody, actor_id=Depends(require_admin_user_id)):
    try:
        with get_db_context() as db:
            account=service.require_account(db)
            revision=account.revision
            row=db.query(models.PixivArtwork).filter_by(account_revision=revision,pid=body.pid).first()
            if row:
                if not allowed(row.metadata_json,account.preferences):raise PixivError('content_filtered')
                return public_art(db,row,actor_id=actor_id)
        with ACCOUNT_LOCK:
            client=service.client_for_job(actor_id,revision)
            try:raw=client.call('illust_detail',illust_id=body.pid).get('illust')
            finally:client.close()
            art=service.normalize_artwork(raw or {})
            if not art or art['pid']!=body.pid:raise PixivError('artwork_unavailable')
            with get_db_context() as db:
                account=service.require_account(db,revision)
                if not allowed(art,account.preferences):raise PixivError('content_filtered')
            service.save_artworks(revision,[raw],'lookup',actor_id)
        with get_db_context() as db:
            account=service.require_account(db,revision)
            row=db.query(models.PixivArtwork).filter_by(account_revision=revision,pid=body.pid).first()
            if not row or not allowed(row.metadata_json,account.preferences):raise PixivError('content_filtered')
            return public_art(db,row,actor_id=actor_id)
    except PixivError as exc:handle_error(exc)


@router.get("/similarity")
def similarity(pid: list[str] = Query(default=[], max_length=24)):
    if any(not value.isascii() or not value.isdigit() or len(value)>30 for value in pid):
        raise HTTPException(422,'无效的 Pixiv PID')
    from ...visual_similarity import match_cached_preview, get_index
    with get_db_context() as db:
        account=service.require_account(db);revision=account.revision
        rows=db.query(models.PixivArtwork).filter(models.PixivArtwork.account_revision==revision,models.PixivArtwork.pid.in_(pid)).all()
        results=[];index=get_index(db)
        for row in rows:
            if not allowed(row.metadata_json,account.preferences):continue
            clear=Path(settings.TEMP_PATH)/'pixiv-ol-viewer'/revision/f'{row.pid}_p0-preview.img'
            thumb=Path(settings.DATA_PATH)/'pixiv_ol_previews'/revision/f'{row.pid}.webp'
            path=clear if clear.is_file() else thumb
            results.append({'pid':row.pid,'matches':match_cached_preview(db,path,index) if path.is_file() else []})
        return {'items':results}


@router.get("/artworks/{pid}/original")
def artwork_original(pid: str, page: int = Query(0, ge=0, le=999)):
    from ...integrations.pixiv_ol.viewer import original

    with get_db_context() as db:
        account = service.require_account(db)
        row = db.query(models.PixivArtwork).filter_by(account_revision=account.revision, pid=pid).first()
        if not row or not allowed(row.metadata_json, account.preferences):
            raise HTTPException(404, "作品不可用")
        art, revision = dict(row.metadata_json), account.revision
    try:
        path, kind = original(art, revision, page)
    except PixivError as exc:
        handle_error(exc)
    with get_db_context() as db:
        account = service.require_account(db, revision)
        if not allowed(art, account.preferences):
            raise HTTPException(404, "作品不可用")
    return FileResponse(path, media_type=kind, headers={"Cache-Control": "private, no-store"})


@router.get("/artworks/{pid}/reader-preview")
def reader_preview(pid: str, request: Request, page: int = Query(0, ge=0, le=999)):
    from ...integrations.pixiv_ol.viewer import clear_preview

    with get_db_context() as db:
        try:
            account = service.require_account(db)
        except PixivError:
            raise HTTPException(404, "作品不可用") from None
        row = db.query(models.PixivArtwork).filter_by(account_revision=account.revision, pid=pid).first()
        if not row or not allowed(row.metadata_json, account.preferences):
            raise HTTPException(404, "作品不可用")
        art, revision = dict(row.metadata_json), account.revision
    try:
        path, kind = clear_preview(art, revision, page)
        with get_db_context() as db:
            account = service.require_account(db, revision)
            row = db.query(models.PixivArtwork).filter_by(account_revision=revision, pid=pid).first()
            if not row or not allowed(row.metadata_json, account.preferences):
                raise HTTPException(404, "作品不可用")
    except PixivError as exc:
        handle_error(exc)
    return private_media(path, kind, request, revision)


@router.get("/cart/{cart_id}/reader-preview")
def cart_reader_preview(cart_id: str, request: Request, page: int = Query(0, ge=0, le=999), actor_id=Depends(require_admin_user_id)):
    from ...integrations.pixiv_ol.cart import require_item
    from ...integrations.pixiv_ol.viewer import clear_preview

    with get_db_context() as db:
        try:
            account = service.require_account(db)
            item = require_item(db, cart_id, account.revision, actor_id)
        except PixivError:
            raise HTTPException(404, "暂存作品不存在") from None
        if not allowed(item.metadata_json, account.preferences) or page not in item.pages:
            raise HTTPException(404, "该页未加入暂存")
        art, revision = dict(item.metadata_json), account.revision
    try:
        path, kind = clear_preview(art, revision, page)
        with get_db_context() as db:
            account = service.require_account(db, revision)
            item = require_item(db, cart_id, revision, actor_id)
            if page not in item.pages or not allowed(item.metadata_json, account.preferences):
                raise HTTPException(404, "作品不可用")
    except PixivError as exc:
        handle_error(exc)
    return private_media(path, kind, request, revision)


@router.get("/artworks/{pid}/avatar")
def artwork_avatar(pid: str, request: Request, actor_id=Depends(require_admin_user_id)):
    from ...integrations.pixiv_ol.viewer import avatar

    with get_db_context() as db:
        try:
            account = service.require_account(db)
        except PixivError:
            raise HTTPException(404, "画师头像不可用") from None
        row = db.query(models.PixivArtwork).filter_by(account_revision=account.revision, pid=pid).first()
        if not row or not allowed(row.metadata_json, account.preferences):
            raise HTTPException(404, "作品不可用")
        art, revision = dict(row.metadata_json), account.revision
    try:
        if "author_avatar" not in art:
            # Recheck after waiting and reuse another work by this artist before calling Pixiv.
            with ACCOUNT_LOCK:
                with get_db_context() as db:
                    account = service.require_account(db, revision)
                    row = db.query(models.PixivArtwork).filter_by(account_revision=revision, pid=pid).first()
                    if not row or not allowed(row.metadata_json, account.preferences):
                        raise HTTPException(404, "作品不可用")
                    art = dict(row.metadata_json)
                    if "author_avatar" not in art:
                        peers = (
                            db.query(models.PixivArtwork)
                            .filter_by(account_revision=revision, author_id=row.author_id)
                            .limit(30)
                            .all()
                        )
                        shared = next(
                            (
                                peer.metadata_json.get("author_avatar")
                                for peer in peers
                                if peer.metadata_json.get("author_avatar")
                            ),
                            None,
                        )
                        if shared:
                            art["author_avatar"] = shared
                            row.metadata_json = art
                if "author_avatar" not in art:
                    client = service.client_for_job(actor_id, revision)
                    try:
                        raw = client.call("illust_detail", illust_id=pid).get("illust")
                    finally:
                        client.close()
                    if not raw or str(raw.get("id")) != pid:
                        raise PixivError("preview_unavailable")
                    service.save_artworks(revision, [raw], "detail", actor_id)
            with get_db_context() as db:
                account = service.require_account(db, revision)
                row = db.query(models.PixivArtwork).filter_by(account_revision=revision, pid=pid).first()
                if not row or not allowed(row.metadata_json, account.preferences):
                    raise HTTPException(404, "作品不可用")
                art = dict(row.metadata_json)
        path, kind = avatar(art, revision)
        with get_db_context() as db:
            account = service.require_account(db, revision)
            row = db.query(models.PixivArtwork).filter_by(account_revision=revision, pid=pid).first()
            if not row or not allowed(row.metadata_json, account.preferences):
                raise HTTPException(404, "作品不可用")
    except PixivError as exc:
        handle_error(exc)
    return private_media(path, kind, request, revision)


@router.get("/cart/{cart_id}/original")
def cart_original(cart_id: str, page: int = Query(0, ge=0, le=999), actor_id=Depends(require_admin_user_id)):
    from ...integrations.pixiv_ol.cart import require_item, cached_path
    from ...integrations.pixiv_ol.viewer import image_type

    with get_db_context() as db:
        try:
            account = service.require_account(db)
            item = require_item(db, cart_id, account.revision, actor_id)
        except PixivError:
            raise HTTPException(404, "暂存作品不存在") from None
        if not allowed(item.metadata_json, account.preferences):
            raise HTTPException(404, "作品不可用")
        try:
            path = cached_path(item, page)
            kind = image_type(path)
        except (PixivError, OSError):
            raise HTTPException(404, "该页原图尚未缓存") from None
    return FileResponse(path, media_type=kind, headers={"Cache-Control": "private, no-store"})


@router.get("/recommendations")
def recommendations(
    batch_id: str | None = None,
    mode: Literal["personal", "stock", "discovery", "combined", "native"] = "combined",
    offset: int = Query(0, ge=0),
    limit: int = Query(20, ge=1, le=50),
    actor_id=Depends(require_admin_user_id),
):
    with get_db_context() as db:
        account = db.get(models.PixivAccount, 1)
        if not account:
            return {"items": [], "total": 0, "batch_id": None}
        query = db.query(models.PixivRecommendationBatch).filter_by(account_revision=account.revision, mode=mode)
        if mode in ('personal', 'stock', 'discovery'):
            query = query.filter(models.PixivRecommendationBatch.profile['actor_id'].as_integer() == actor_id)
        if mode == 'stock' and not batch_id:
            from ...integrations.pixiv_ol.strategies import POLICY_VERSION
            query = query.filter(models.PixivRecommendationBatch.profile['policy_version'].as_string() == POLICY_VERSION)
        batch = (
            query.filter_by(id=batch_id).first()
            if batch_id
            else query.order_by(models.PixivRecommendationBatch.created_at.desc()).first()
        )
        if not batch:
            return {"items": [], "total": 0, "batch_id": None}
        pids = [item['pid'] for item in batch.items]
        excluded = set(library_pixiv_pages(db, pids))
        excluded.update(row[0] for row in db.query(models.PixivCartItem.pid).filter(
            models.PixivCartItem.account_revision == account.revision,
            models.PixivCartItem.actor_id == actor_id,
            models.PixivCartItem.pid.in_(pids),
        ).all())
        items = [(position, item) for position, item in enumerate(batch.items)
                 if item['pid'] not in excluded and allowed(item, account.preferences)]
        # Offsets refer to the immutable batch, not the shrinking visible list.
        # Adding/importing earlier cards must not skip unseen cards on continuation.
        remaining = [(position, item) for position, item in items if position >= offset]
        if mode == 'stock':
            from ...integrations.pixiv_ol.strategies import stock_page
            page = stock_page(remaining, limit)
        else:
            page = remaining[:limit]
        next_offset = page[-1][0] + 1 if page else len(batch.items)
        output = [
            {
                **{k: v for k, v in i.items() if k not in ("preview", "originals", "page_previews", "author_avatar")},
                "preview_url": f"/api/pixiv-ol/previews/{i['pid']}",
                "original_url": f"/api/pixiv-ol/artworks/{i['pid']}/original",
                "reader_preview_url": f"/api/pixiv-ol/artworks/{i['pid']}/reader-preview",
                "author_avatar_url": f"/api/pixiv-ol/artworks/{i['pid']}/avatar",
            }
            for _, i in page
        ]
        for item in output:
            item['imported_pages'] = []
        likes = {
            x[0]
            for x in db.query(models.PixivFeedback.pid)
            .filter(
                models.PixivFeedback.account_revision == account.revision,
                models.PixivFeedback.actor_id == actor_id,
                models.PixivFeedback.value == "like",
                models.PixivFeedback.pid.in_([i["pid"] for i in output]),
            )
            .all()
        }
        for item in output:
            item["liked"] = item["pid"] in likes
        return {"items": output, "total": len(items), "batch_id": batch.id, "profile": {} if mode == 'personal' else batch.profile,
                "next_offset": next_offset, "has_more": any(position >= next_offset for position, _ in items)}


@router.get("/previews/{pid}")
def preview(pid: str, request: Request):
    with get_db_context() as db:
        account = service.require_account(db)
        row = db.query(models.PixivArtwork).filter_by(account_revision=account.revision, pid=pid).first()
        if not row or not allowed(row.metadata_json, account.preferences):
            raise HTTPException(404, "预览不存在")
        revision, url = account.revision, row.metadata_json.get("preview")
        canonical_pid = row.pid
    path = Path(settings.DATA_PATH) / "pixiv_ol_previews" / revision / f"{canonical_pid}.webp"
    path.parent.mkdir(parents=True, exist_ok=True)
    from ...integrations.pixiv_ol.viewer import file_lock, ENCODE_SLOTS

    with file_lock(path):
        if not path.is_file():
            stage = path.with_name(f"{path.stem}-{secrets.token_hex(4)}.tmp")
            try:
                download(url, stage, limit=5 * 1024 * 1024, lane="preview")
                from PIL import Image

                with Image.open(stage) as image:
                    image.verify()
                with ENCODE_SLOTS, Image.open(stage) as image:
                    if image.width * image.height > 50_000_000:
                        raise ValueError("image dimensions")
                    image.thumbnail((800, 800))
                    image.convert("RGB").save(stage, format="WEBP", quality=82)
                stage.replace(path)
            except Exception:
                stage.unlink(missing_ok=True)
                raise HTTPException(502, "preview_unavailable") from None
    with get_db_context() as db:
        account = service.require_account(db, revision)
        row = db.query(models.PixivArtwork).filter_by(account_revision=revision, pid=pid).first()
        if not row or not allowed(row.metadata_json, account.preferences):
            raise HTTPException(404, "预览已失效")
    return private_media(path, "image/webp", request, revision)


@router.post("/imports", status_code=202, dependencies=[Depends(write_guard)])
def imports(body: ImportBody, actor_id=Depends(require_admin_user_id)):
    draft = body.model_dump()
    if any(p < 0 or p > 999 for p in body.pages):
        raise HTTPException(422, "页码无效")
    draft["pages"] = sorted(set(body.pages))
    draft["new_tags"] = list({normalize(x): x.strip() for x in body.new_tags if x.strip()}.values())
    if any(len(x) > 255 for x in draft["new_tags"]):
        raise HTTPException(422, "标签过长")
    try:
        with get_db_context() as db:
            from ...integrations.pixiv_ol.jobs import validate_draft

            validate_draft(db, {**draft, "actor_id": actor_id})
            job = enqueue(db, actor_id, "import", draft, body.idempotency_key)
            return job_json(job)
    except PixivError as exc:
        handle_error(exc)
    except IntegrityError:
        raise HTTPException(409, "相同入库请求已创建") from None


@router.get("/imports/{job_id}/comparison")
def import_comparison(job_id: int, actor_id=Depends(require_admin_user_id)):
    from ...integrations.pixiv_ol import cart, import_review
    from ...integrations.pixiv_ol.import_review import signature
    with get_db_context() as db:
        account = service.require_account(db)
        service.require_actor(db, actor_id)
        job = db.get(models.PixivJob, job_id)
        if not job or job.account_revision != account.revision or job.actor_id != actor_id or job.status != "awaiting_duplicate":
            raise HTTPException(409, "任务不在查重等待状态")
        signatures = job.result.get("candidate_signatures", {})
        changed = any(not (image := db.get(models.Image, image_id)) or signature(image) != expected
                      for image_id, expected in signatures.items())
        if (changed or not job.result.get("incoming")) and not job.payload.get("cart_id"):
            page = str(job.result['page'])
            decisions = {key: value for key, value in job.payload.get('decisions', {}).items() if key != page}
            job.payload = {**job.payload, 'decisions': decisions}
            job.status = 'queued'
            db.commit()
            raise HTTPException(409, '图片或标签已变化，正在重新比对')
        if not job.result.get("incoming") or changed:
            # Upgrade an older durable waiting job when its cached cart survives.
            item = cart.require_item(db, job.payload.get("cart_id"), account.revision, actor_id)
            page = job.result["page"]
            from ...integrations.pixiv_ol.jobs import page_draft
            tags = page_draft({**job.payload, "actor_id": actor_id}, page)
            source = cart.cached_path(item, page)
            matches = import_review.candidates(db, source, ImageService.compute_dhash(str(source)), tags['group_ids']) if changed else job.result['duplicates']
            if not matches:
                job.status = 'queued'
                db.commit()
                raise HTTPException(409, '相似候选已变化，正在重新比对')
            job.result = import_review.review(db, item.metadata_json, page, tags, source,
                matches, job.result.get("done", []), item.id)
        return job.result


@router.post("/imports/{job_id}/resolve", status_code=202, dependencies=[Depends(write_guard)])
def resolve(job_id: int, body: ResolveBody, actor_id=Depends(require_admin_user_id)):
    from sqlalchemy import update
    from ...integrations.pixiv_ol.import_review import signature
    with get_db_context() as db:
        account = service.require_account(db)
        service.require_actor(db, actor_id)
        job = db.get(models.PixivJob, job_id)
        if not job or job.account_revision != account.revision or job.actor_id != actor_id or job.status != "awaiting_duplicate":
            raise HTTPException(409, "任务不在查重等待状态")
        result = job.result
        if (body.page is not None and body.page != result["page"]) or (body.review_key and body.review_key != result.get("review_key")):
            raise HTTPException(409, "比对页已变化，请重新打开")
        decision = body.model_dump()
        if body.action != "different":
            if body.image_id not in {row["image_id"] for row in result.get("duplicates", [])}:
                raise HTTPException(409, "相似候选已变化")
            image = db.get(models.Image, body.image_id)
            expected = result.get("candidate_signatures", {}).get(body.image_id)
            if not image or image.file_status != "available" or expected and signature(image) != expected:
                raise HTTPException(409, "图片或标签已变化，请重新比对")
            if body.action.startswith("merge_") and not ImageService.image_file_exists(image):
                raise HTTPException(409, "库内文件已缺失")
            decision["candidate_signature"] = signature(image)
        page = str(result["page"])
        payload = {**job.payload, "decisions": {**job.payload.get("decisions", {}), page: decision}}
        claimed = db.execute(update(models.PixivJob).where(models.PixivJob.id == job_id,
            models.PixivJob.status == "awaiting_duplicate").values(payload=payload, status="queued", error=None).returning(models.PixivJob.id)).scalar_one_or_none()
        if claimed is None:
            raise HTTPException(409, "本次确认已处理")
        db.expire(job)
        return job_json(job)


@router.get("/preferences")
def preferences():
    with get_db_context() as db:
        account = db.get(models.PixivAccount, 1)
        association = models.image_group_association
        counts = dict(
            db.query(association.c.group_id, func.count(association.c.image_id))
            .join(models.Image, models.Image.image_id == association.c.image_id)
            .filter(models.Image.file_status == "available")
            .group_by(association.c.group_id)
            .all()
        )
        from ...integrations.pixiv_ol.strategies import inverse_weights

        counts = {x[0]: counts.get(x[0], 0) for x in db.query(models.Group.id).all()}
        prefs = account.preferences if account else {}
        selected = {g:n for g, n in counts.items() if prefs.get('groups', {}).get(str(g), {}).get('enabled', n > 0)}
        return {**prefs, "inventory": counts, "quotas": inverse_weights(selected)}


@router.put("/preferences", dependencies=[Depends(write_guard), Depends(require_root_user_id)])
def set_preferences(body: PreferencesBody):
    with get_db_context() as db:
        account = service.require_account(db)
        valid = {str(x[0]) for x in db.query(models.Group.id).all()}
        if not set(body.groups).issubset(valid):
            raise HTTPException(422, "分组不存在")
        account.preferences = body.model_dump()
    return {"saved": True}


def mark_liked(db, revision, actor_id, pid):
    row = db.query(models.PixivFeedback).filter_by(account_revision=revision, actor_id=actor_id, pid=pid).first()
    if not row:
        row = models.PixivFeedback(account_revision=revision, actor_id=actor_id, pid=pid)
        db.add(row)
    row.value = "like"
    db.flush()


@router.post("/feedback", dependencies=[Depends(write_guard)])
def feedback(body: FeedbackBody, actor_id=Depends(require_admin_user_id)):
    with get_db_context() as db:
        account = service.require_account(db)
        row = (
            db.query(models.PixivFeedback)
            .filter_by(account_revision=account.revision, actor_id=actor_id, pid=body.pid)
            .first()
        )
        if body.value == "clear":
            if row:
                db.delete(row)
        else:
            if not row:
                row = models.PixivFeedback(account_revision=account.revision, actor_id=actor_id, pid=body.pid)
                db.add(row)
            row.value = body.value
    return {"saved": True}


@router.get("/tag-mappings")
def mappings(target_type: Literal["group", "character", "feature", "ignore"] | None = None, target_id: int | None = None):
    with get_db_context() as db:
        query = db.query(models.PixivTagMapping)
        if target_type: query = query.filter_by(target_type=target_type)
        if target_id is not None: query = query.filter_by(target_id=target_id)
        return [
            {
                "id": x.id,
                "tag": x.original_tag or x.normalized_tag,
                "source": x.source,
                "group_context": x.group_context,
                "target_type": x.target_type,
                "target_id": x.target_id,
            }
            for x in query.order_by(models.PixivTagMapping.id).all()
        ]


@router.post("/tag-mappings", dependencies=[Depends(write_guard), Depends(require_root_user_id)])
def save_mapping(body: MappingBody):
    with get_db_context() as db:
        from ...tag_mappings import save_mapping as persist
        try: persist(db, body.tag, body.target_type, body.target_id, body.group_context, replace=body.replace)
        except ValueError as exc: raise HTTPException(422, str(exc)) from None
    return {"saved": True}


@router.post("/tag-mappings/batch", dependencies=[Depends(write_guard), Depends(require_root_user_id)])
def save_mapping_batch(body: MappingBatchBody):
    from ...tag_mappings import save_mapping as persist
    with get_db_context() as db:
        try:
            for binding in body.bindings:
                if binding.replace or binding.target_type == 'ignore':
                    raise ValueError('批量关联只能添加标签，请单独处理忽略或替换')
                persist(db, binding.tag, binding.target_type, binding.target_id, binding.group_context)
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from None
    return {"saved": True}


@router.delete("/tag-mappings/{mapping_id}", dependencies=[Depends(write_guard), Depends(require_root_user_id)])
def delete_mapping(mapping_id: int):
    with get_db_context() as db:
        row = db.get(models.PixivTagMapping, mapping_id)
        if not row:
            raise HTTPException(404, "映射不存在")
        db.delete(row)
    return {"deleted": True}
