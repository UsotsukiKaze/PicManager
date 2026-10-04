"""Cached account state and resumable synchronization; no network inside transactions."""

import secrets
from datetime import datetime, timedelta, timezone

from sqlalchemy import update

from ... import models
from ...database import get_db_context
from .provider import Provider, PixivError, encrypt, decrypt, plain
from .recommendations import TagIndex, build_profile, rank_candidates


def iso_date(value):
    try:
        date = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return date.astimezone(timezone.utc).replace(tzinfo=None) if date.tzinfo else date
    except (TypeError, ValueError):
        raise PixivError("invalid_metadata") from None


def normalize_artwork(raw):
    raw = plain(raw)
    pid = str(raw.get("id", ""))
    user = raw.get("user") or {}
    rating = raw.get("x_restrict")
    if not pid.isdigit() or rating not in (0, 1, 2) or raw.get("type") == "ugoira" or raw.get("visible") is False:
        return None
    pages = raw.get("meta_pages") or []
    originals = [p.get("image_urls", {}).get("original", "") for p in pages]
    if not originals:
        originals = [raw.get("meta_single_page", {}).get("original_image_url", "")]
    return {
        "pid": pid,
        "title": str(raw.get("title", ""))[:500],
        "author_id": str(user.get("id", "")),
        "author": str(user.get("name", ""))[:100],
        "author_avatar": (user.get("profile_image_urls") or {}).get("medium", ""),
        "published_at": iso_date(raw.get("create_date")).isoformat(),
        "page_count": max(1, min(1000, int(raw.get("page_count", 1)))),
        "originals": originals,
        "preview": raw.get("image_urls", {}).get("medium", ""),
        "page_previews": [
            p.get("image_urls", {}).get("large")
            or p.get("image_urls", {}).get("medium")
            or p.get("image_urls", {}).get("original", "")
            for p in pages
        ]
        or [raw.get("image_urls", {}).get("large") or raw.get("image_urls", {}).get("medium", "")],
        "x_restrict": rating,
        "ai_type": raw.get("illust_ai_type"),
        "tags": [
            {"name": str(t.get("name", ""))[:255], "translated_name": t.get("translated_name")}
            for t in raw.get("tags", [])[:100]
            if t.get("name")
        ],
        "bookmarks": raw.get("total_bookmarks"),
        "type": raw.get("type", "illust"),
    }


def require_account(db, revision=None):
    account = db.get(models.PixivAccount, 1)
    if not account or (revision and account.revision != revision):
        raise PixivError("account_changed")
    return account


def require_actor(db, actor_id):
    user = db.get(models.User, actor_id)
    if not user or user.role not in ("root", "admin"):
        raise PixivError("permission_revoked")
    return user


def connect(token, actor_id):
    with get_db_context() as db:
        old = db.get(models.PixivAccount, 1)
        previous = old.revision if old else None
    provider = Provider(token)
    try:
        return store_connection(provider.token, provider.user, actor_id, previous)
    finally:
        provider.close()


def connect_cli(token, user, actor_id, session_id):
    """The CLI already exchanged and verified this account; do not rotate it a second time."""
    with get_db_context() as db:
        old = db.get(models.PixivAccount, 1)
        previous = old.revision if old else None
    return store_connection(token, user, actor_id, previous, session_id)


def store_connection(token, user, actor_id, previous, session_id=None):
    # Serialize against the local worker in the caller; CAS handles other processes.
    old_cart_ids = []
    try:
        credential = encrypt(token)
        with get_db_context() as db:
            account = db.get(models.PixivAccount, 1)
            if (account.revision if account else None) != previous:
                raise PixivError("account_changed")
            require_actor(db, actor_id)
            if session_id:
                from .login import require_root

                require_root(db, actor_id)
                session = db.get(models.PixivLoginSession, session_id)
                if not session or session.actor_id != actor_id or session.status != "exchanging" or session.verifier:
                    raise PixivError("login_cancelled")
                if session.expires_at <= datetime.utcnow():
                    raise PixivError("login_expired")
                session.status = "completed"
            account_changed = not account or account.user_id != user["id"]
            if account and account_changed:
                old_cart_ids = [row[0] for row in db.query(models.PixivCartItem.id).all()]
                db.query(models.PixivCartItem).delete()
                db.query(models.PixivJob).filter(models.PixivJob.status.in_(("queued", "retry", "running"))).update(
                    {"status": "cancelled", "dedupe_key": None}
                )
                db.query(models.PixivArtwork).delete()
                db.query(models.PixivFollow).delete()
                db.query(models.PixivRecommendationBatch).delete()
                db.query(models.PixivFeedback).delete()
            elif not account:
                account = models.PixivAccount(id=1)
                db.add(account)
            account.user_id, account.name = user["id"], user["name"]
            account.owner_id, account.credential = actor_id, credential
            if account_changed:
                account.revision = secrets.token_hex(16)
                account.preferences, account.sync_state = {}, {}
            account.status = "connected"
        return {"connected": True, "name": user["name"]}
    finally:
        if old_cart_ids:
            from .cart import cleanup

            with get_db_context() as db:
                deleted = [id_ for id_ in old_cart_ids if db.get(models.PixivCartItem, id_) is None]
            for id_ in deleted:
                cleanup(id_)


def client_for_job(actor_id, revision):
    with get_db_context() as db:
        account = require_account(db, revision)
        require_actor(db, actor_id)
        credential, user_id = account.credential, account.user_id
    provider = Provider(decrypt(credential))
    try:
        if provider.user["id"] != user_id:
            raise PixivError("account_changed")
        updated = encrypt(provider.token)
        with get_db_context() as db:
            require_actor(db, actor_id)
            changed = db.execute(
                update(models.PixivAccount)
                .where(
                    models.PixivAccount.id == 1,
                    models.PixivAccount.revision == revision,
                    models.PixivAccount.credential == credential,
                )
                .values(credential=updated, status="connected")
            ).rowcount
            if not changed:
                raise PixivError("account_changed")
        return provider
    except Exception:
        provider.close()
        raise


def save_artworks(revision, raws, source, actor_id, *, ranks=False, rank_offset=0, source_batch=None):
    with get_db_context() as db:
        require_account(db, revision)
        require_actor(db, actor_id)
        for position, raw in enumerate(raws):
            art = normalize_artwork(raw)
            if art is None:
                continue
            row = db.query(models.PixivArtwork).filter_by(account_revision=revision, pid=art["pid"]).first()
            if not row:
                row = models.PixivArtwork(account_revision=revision, pid=art["pid"], origins=[])
                db.add(row)
            row.author_id, row.title = art["author_id"], art["title"]
            row.published_at, row.metadata_json = iso_date(art["published_at"]), art
            row.fetched_at = datetime.utcnow()
            origins = [o for o in row.origins if o["source"] != source]
            row.origins = [
                *origins,
                {"source": source, "rank": rank_offset + position + 1 if ranks else None, "batch": source_batch},
            ]
            db.flush()


def sync_feed(provider, revision, actor_id, restrict="public"):
    key = f"feed_{restrict}"
    with get_db_context() as db:
        account = require_account(db, revision)
        state = dict(account.sync_state.get(key, {}))
    cutoff = (
        iso_date(state["cutoff"])
        if state.get("cursor")
        else (
            iso_date(state["last_success"]) - timedelta(hours=48)
            if state.get("last_success")
            else datetime.utcnow() - timedelta(days=7)
        )
    )
    cursor, count = state.get("cursor") or {}, 0
    for _ in range(5):
        response = provider.call("illust_follow", restrict=restrict, **cursor)
        raws = response.get("illusts", [])
        save_artworks(revision, raws, f"feed_{restrict}", actor_id)
        count += len(raws)
        dates = [iso_date(r["create_date"]) for r in raws if r.get("create_date")]
        cursor = provider.cursor(response.get("next_url"))
        finished = not cursor or (dates and min(dates) < cutoff)
        with get_db_context() as db:
            account = require_account(db, revision)
            require_actor(db, actor_id)
            history_matches = "history_cursor" not in state or state.get("history_cursor") == state.get("cursor")
            state = {**state, "cursor": None if finished else cursor, "cutoff": cutoff.isoformat()}
            if history_matches:
                state["history_cursor"] = cursor
            if finished:
                state["last_success"] = datetime.utcnow().isoformat()
            account.sync_state = {**account.sync_state, key: state}
        if finished:
            return {"count": count, "partial": False}
    return {"count": count, "partial": True}


def sync_following(provider, revision, actor_id, restrict="public"):
    key = f"following_{restrict}"
    with get_db_context() as db:
        account = require_account(db, revision)
        state = dict(account.sync_state.get(key, {}))
        user_id = account.user_id
    marker = state.get("marker") or secrets.token_hex(16)
    cursor, count = state.get("cursor") or {}, 0
    for _ in range(5):
        response = provider.call("user_following", user_id=user_id, restrict=restrict, **cursor)
        cursor = provider.cursor(response.get("next_url"))
        with get_db_context() as db:
            account = require_account(db, revision)
            require_actor(db, actor_id)
            for entry in response.get("user_previews", []):
                user = entry["user"]
                author_id = str(user["id"])
                row = db.query(models.PixivFollow).filter_by(account_revision=revision, author_id=author_id).first()
                if not row:
                    row = models.PixivFollow(account_revision=revision, author_id=author_id)
                    db.add(row)
                row.name, row.restrict, row.sync_marker = user["name"], restrict, marker
                db.flush()
                count += 1
            state = {"cursor": cursor, "marker": marker if cursor else None}
            if not cursor:
                db.query(models.PixivFollow).filter(
                    models.PixivFollow.account_revision == revision,
                    models.PixivFollow.restrict == restrict,
                    models.PixivFollow.sync_marker != marker,
                ).delete()
                state["last_success"] = datetime.utcnow().isoformat()
            account.sync_state = {**account.sync_state, key: state}
        if not cursor:
            return {"count": count, "partial": False}
    return {"count": count, "partial": True}


def continue_feed(provider, revision, actor_id, restrict="public"):
    """Read older following posts independently from incremental latest-post sync."""
    with get_db_context() as db:
        account = require_account(db, revision)
        key = f"feed_{restrict}"
        state = dict(account.sync_state.get(key, {}))
    if state.get("history_exhausted"):
        return {"count": 0, "more": False}
    cursor = state.get("history_cursor") or {}
    count = 0
    for _ in range(2):
        response = provider.call("illust_follow", restrict=restrict, **cursor)
        raws = response.get("illusts", [])
        save_artworks(revision, raws, key, actor_id)
        count += len(raws)
        next_cursor = provider.cursor(response.get("next_url"))
        exhausted = not next_cursor or next_cursor == cursor
        with get_db_context() as db:
            account = require_account(db, revision)
            require_actor(db, actor_id)
            current = dict(account.sync_state.get(key, {}))
            account.sync_state = {
                **account.sync_state,
                key: {**current, "history_cursor": next_cursor, "history_exhausted": exhausted},
            }
        cursor = next_cursor
        if exhausted:
            break
    return {"count": count, "more": not exhausted}


def refresh_candidates(provider, revision, actor_id, mode="combined", *, continuation=False):
    with get_db_context() as db:
        account = require_account(db, revision)
        index = TagIndex(db)
        profile = build_profile(db, index, account.preferences)
        preferences = account.preferences
        stream = dict(account.sync_state.get(f"recommendation_stream_{mode}", {}))
        if continuation and stream.get("exhausted"):
            return {"count": 0, "more": False}
        queries = [
            (g, next((row.original_tag or row.normalized_tag for row in db.query(models.PixivTagMapping).filter_by(target_type="group", target_id=g).order_by(models.PixivTagMapping.id).all()), index.groups[g].name))
            for g in sorted(profile["quotas"], key=lambda x: -profile["quotas"][x])
        ][:10]
        associations = models.image_group_association
        seed_rows = (
            db.query(models.PixivImageSource.work_id, associations.c.group_id)
            .join(associations, associations.c.image_id == models.PixivImageSource.image_id)
            .filter(associations.c.group_id.in_([g for g, _ in queries]))
            .distinct()
            .limit(1000)
            .all()
        )
        seeds = []
        for group, _ in queries:
            candidates = [pid for pid, g in seed_rows if g == group and pid not in seeds]
            if candidates:
                seeds.append(candidates[0])
            if len(seeds) == 4:
                break
    warnings = []
    source_batch = secrets.token_hex(16)
    platform_count = 0
    exhausted = False
    try:
        cursor = (stream.get("cursor") or {}) if continuation else {}
        for _ in range(3 if mode != "native" else 4):
            response = provider.call("illust_recommended", include_ranking_illusts="false", **cursor)
            raws = response.get("illusts", [])
            save_artworks(
                revision,
                raws,
                "recommended",
                actor_id,
                ranks=True,
                rank_offset=platform_count,
                source_batch=source_batch,
            )
            platform_count += len(raws)
            next_cursor = provider.cursor(response.get("next_url"))
            exhausted = not next_cursor or next_cursor == cursor
            cursor = next_cursor
            if exhausted or not raws or platform_count >= 80:
                break
    except PixivError as exc:
        warnings.append(exc.code)
    if continuation and not platform_count and warnings:
        raise PixivError(warnings[0])
    if mode != "native" and not continuation:
        for group, query in queries:
            try:
                response = provider.call("search_illust", word=query, search_target="partial_match_for_tags")
                budget = max(3, int(70 * profile["quotas"][group]))
                save_artworks(
                    revision, response.get("illusts", [])[:budget], "search", actor_id, source_batch=source_batch
                )
            except PixivError as exc:
                warnings.append(exc.code)
        for pid in seeds:
            try:
                response = provider.call("illust_related", illust_id=pid)
                save_artworks(
                    revision, response.get("illusts", [])[:10], "related", actor_id, source_batch=source_batch
                )
            except PixivError as exc:
                warnings.append(exc.code)
    with get_db_context() as db:
        account = require_account(db, revision)
        require_actor(db, actor_id)
        if platform_count:
            account.sync_state = {
                **account.sync_state,
                "recommended": {"batch": source_batch, "last_success": datetime.utcnow().isoformat()},
            }
        account.sync_state = {**account.sync_state, "candidate_batch": source_batch}
        if not warnings or platform_count:
            account.sync_state = {
                **account.sync_state,
                f"recommendation_stream_{mode}": {"cursor": cursor, "exhausted": exhausted},
            }
        items, profile = rank_candidates(db, account, mode)
        batch_id = secrets.token_hex(16)
        db.add(
            models.PixivRecommendationBatch(
                id=batch_id, account_revision=revision, mode=mode, items=items, profile=profile
            )
        )
        old = (
            db.query(models.PixivRecommendationBatch.id)
            .filter_by(account_revision=revision)
            .order_by(models.PixivRecommendationBatch.created_at.desc())
            .offset(9)
            .all()
        )
        if old:
            db.query(models.PixivRecommendationBatch).filter(
                models.PixivRecommendationBatch.id.in_([x[0] for x in old])
            ).delete()
    return {
        "batch_id": batch_id,
        "count": len(items),
        "warnings": sorted(set(warnings)),
        "more": not exhausted if platform_count else bool(warnings),
    }
