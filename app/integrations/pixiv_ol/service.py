"""Cached account state and resumable synchronization; no network inside transactions."""

import secrets
import threading
from datetime import datetime, timedelta, timezone

from sqlalchemy import update

from ... import models
from ...database import get_db_context
from .provider import Provider, PixivError, encrypt, decrypt, plain
from .recommendations import TagIndex, build_profile, rank_candidates, normalize
from .search_plan import build_search_plan, restored_query

CLIENT_LOCK = threading.Lock()  # Serialize refresh-token rotation, not artwork requests.


def current_stock_replenishment(account, actor_id, source_batch):
    from .strategies import stream_key, POLICY_VERSION
    stream = account.sync_state.get(stream_key('stock', actor_id), {})
    return (stream.get('source_batch') == source_batch and stream.get('policy_version') == POLICY_VERSION
            and bool(stream.get('deferred_queries'))
            and (datetime.utcnow() - iso_date(stream.get('started_at', '1970-01-01'))).total_seconds() <= 900)


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
    with CLIENT_LOCK:
        return _client_for_job(actor_id, revision)


def _client_for_job(actor_id, revision):
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
            elif art["bookmarks"] is None and row.metadata_json:
                art["bookmarks"] = row.metadata_json.get("bookmarks")
            row.author_id, row.title = art["author_id"], art["title"]
            row.published_at, row.metadata_json = iso_date(art["published_at"]), art
            row.fetched_at = datetime.utcnow()
            origins = [o for o in row.origins if o["source"] != source]
            row.origins = [
                *origins,
                {"source": source, "rank": rank_offset + position + 1 if ranks else None, "batch": source_batch},
            ]
            db.flush()


def sync_feed(provider, revision, actor_id, restrict="public", *, first_page=False):
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
    for _ in range(1 if first_page else 5):
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
    return {"count": count, "partial": not first_page, "more": True}


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


def continue_feed(provider, revision, actor_id, restrict="public", *, progressive=False):
    """Read older following posts independently from incremental latest-post sync."""
    with get_db_context() as db:
        account = require_account(db, revision)
        key = f"feed_{restrict}"
        state = dict(account.sync_state.get(key, {}))
    if state.get("history_exhausted"):
        return {"count": 0, "more": False}
    cursor = state.get("history_cursor") or {}
    count = 0
    for _ in range(1 if progressive else 2):
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


def refresh_candidates(provider, revision, actor_id, mode="combined", *, continuation=False, progressive=False,
                       seen_pids=(), replenish_batch=None):
    from . import strategies
    progressive = progressive or mode == 'stock'
    independent = mode in strategies.MODES
    stream_name = strategies.stream_key(mode, actor_id)
    recommended_source = strategies.source_key('recommended', mode, actor_id)
    with get_db_context() as db:
        account = require_account(db, revision)
        index = TagIndex(db)
        profile = strategies.build_profile(db, index, account, mode) if independent else build_profile(db, index, account.preferences)
        preferences = account.preferences
        stream = dict(account.sync_state.get(stream_name, {}))
        if replenish_batch is not None and (mode != 'stock' or not current_stock_replenishment(account, actor_id, replenish_batch)):
            return {'count':0, 'more':False, 'replenish':False}
        if mode in ('personal', 'stock') and stream.get('policy_version') != strategies.POLICY_VERSION:
            continuation = False
        if independent and continuation and not stream:
            continuation = False
        deferred = bool(stream.get("deferred_queries") or stream.get("deferred_seeds"))
        cached_only = bool(continuation and stream.get('exhausted') and not deferred)
        if cached_only and mode != 'stock':
            return {"count": 0, "more": False}
        query_round = int(stream.get("query_round", -1)) + (0 if continuation else 1)
        queries = (strategies.search_plan(db, index, profile, preferences, mode, max(0, query_round)) if independent
                   else build_search_plan(db, index, profile, preferences, rotation=max(0, query_round)))
        seeds = []
        for group in sorted(profile["quotas"], key=lambda g: -profile["quotas"][g]):
            candidates = [pid for pid in profile["related_seeds"].get(group, []) if pid not in seeds]
            if candidates:
                seeds.append(candidates[0])
            if len(seeds) == 4:
                break
        if mode == 'personal':
            seeds = profile['personal_seeds']
    warnings = []
    source_batch = (stream.get('source_batch') if independent and continuation else None) or secrets.token_hex(16)
    native_offset = int(stream.get('native_offset', 0)) if independent and continuation else 0
    platform_count = 0
    exhausted = bool(continuation and stream.get("exhausted"))
    pending_queries = [restored_query(row) for row in stream.get("deferred_queries", [])] if continuation else list(queries)
    blocked = {normalize(tag) for tag in preferences.get('blocked_tags', [])}
    pending_queries = [query for query in pending_queries if (query["group"] in profile["quotas"] or independent and query['group'] is None)
                       and not any(normalize(term) in blocked or
                                   index.is_ignored(term, query['group'])
                                   for term in query.get('terms', [query['word']]))]
    pending_seeds = list(stream.get("deferred_seeds", [])) if continuation else list(seeds)
    if mode in ("native", "discovery"):
        pending_queries, pending_seeds = [], []
    local_count = 0
    try:
        cursor = (stream.get("cursor") or {}) if continuation else {}
        pages = 1 if progressive else (4 if mode in ("native", "discovery") else 3)
        for _ in range(0 if exhausted or replenish_batch is not None else pages):
            response = provider.call("illust_recommended", include_ranking_illusts="false", **cursor)
            raws = response.get("illusts", [])
            save_artworks(
                revision,
                raws,
                recommended_source,
                actor_id,
                ranks=True,
                rank_offset=native_offset + platform_count,
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
    if mode not in ("native", "discovery") and (not continuation or progressive):
        query_slice = pending_queries[:1] if progressive and continuation else ([] if progressive else list(pending_queries))
        if mode == 'stock' and progressive and pending_queries:
            with get_db_context() as db:
                account = require_account(db, revision)
                recall_index = TagIndex(db)
                candidates = strategies._candidates(db, recall_index, account, mode, actor_id,
                                                    seen_pids if continuation else (), source_batch=source_batch)
                query_slice = strategies.stock_recall_queries(pending_queries, candidates, profile, recall_index)
        seed_slice = pending_seeds[:1] if progressive and continuation and not query_slice else ([] if progressive else list(pending_seeds))
        responses = None
        if mode == 'stock' and query_slice and callable(getattr(provider, 'call_many', None)):
            responses = provider.call_many([('search_illust', {**query.get('cursor', {}), 'word':query['word'], 'search_target':query['search_target']})
                                            for query in query_slice], workers=3)
        for position, query in enumerate(query_slice):
            try:
                response = responses[position] if responses is not None else provider.call(
                    "search_illust", **query.get('cursor', {}), word=query["word"], search_target=query["search_target"])
                if isinstance(response, PixivError):
                    raise response
                group = query["group"]
                budget = 30 if mode == 'stock' else (20 if group is None else max(3, int(70 * profile["quotas"][group])))
                save_artworks(
                    revision, response.get("illusts", [])[:budget], strategies.source_key('search', mode, actor_id), actor_id, source_batch=source_batch
                )
                local_count += len(response.get("illusts", [])[:budget])
                pending_queries.remove(query)
                if mode == 'stock':
                    next_cursor = provider.cursor(response.get('next_url'))
                    query['pages'] = int(query.get('pages', 0)) + 1
                    if next_cursor and next_cursor != query.get('cursor') and query['pages'] < 3:
                        with get_db_context() as db:
                            account = require_account(db, revision)
                            recall_index = TagIndex(db)
                            candidates = strategies._candidates(db, recall_index, account, mode, actor_id,
                                seen_pids if continuation else (), source_batch=source_batch)
                            groups, roles = strategies.stock_supply(candidates, profile, recall_index)
                        group_gap, role_gap = strategies.stock_query_gap(query, profile, groups, roles)
                        gap = role_gap if query.get('character') is not None else group_gap
                        if gap > 0:
                            pending_queries.append({**query, 'cursor':next_cursor, 'attempts':0})
            except PixivError as exc:
                warnings.append(exc.code)
                if mode == 'stock':
                    # A broken query cannot monopolize the background queue.
                    query['attempts'] = int(query.get('attempts', 0)) + 1
                    if query in pending_queries:
                        pending_queries.remove(query)
                    if query['attempts'] < 3:
                        pending_queries.append(query)
                    if exc.code == 'reauth_required':
                        raise
        for pid in seed_slice:
            try:
                response = provider.call("illust_related", illust_id=pid)
                save_artworks(
                    revision, response.get("illusts", [])[:10], strategies.source_key('related', mode, actor_id), actor_id, source_batch=source_batch
                )
                local_count += len(response.get("illusts", [])[:10])
                pending_seeds.remove(pid)
            except PixivError as exc:
                warnings.append(exc.code)
    if mode != 'stock' and (continuation or independent) and not platform_count and not local_count and warnings:
        raise PixivError(warnings[0])
    with get_db_context() as db:
        account = require_account(db, revision)
        require_actor(db, actor_id)
        if platform_count or (independent and not cached_only):
            account.sync_state = {
                **account.sync_state,
                recommended_source: {"batch": source_batch, "last_success": datetime.utcnow().isoformat()},
            }
        if not independent:
            account.sync_state = {**account.sync_state, "candidate_batch": source_batch}
        if not warnings or platform_count or local_count or mode == 'stock':
            account.sync_state = {
                **account.sync_state,
                stream_name: {"cursor": cursor, "exhausted": exhausted, "query_round": query_round,
                    "policy_version": strategies.POLICY_VERSION,
                    "source_batch": source_batch, "native_offset": native_offset + platform_count,
                    "started_at": stream.get('started_at') if continuation and stream.get('started_at') else datetime.utcnow().isoformat(),
                    "deferred_queries": pending_queries if progressive else [],
                    "deferred_seeds": pending_seeds if progressive else []},
            }
        if replenish_batch is not None and pending_queries:
            # Warm supply without creating/pruning immutable reading batches
            # for every small background wave. Publish once when warming ends.
            return {'count':local_count, 'warnings':sorted(set(warnings)), 'more':True,
                    'replenish':True, 'source_batch':source_batch}
        items, profile = rank_candidates(db, account, mode, actor_id=actor_id, seen_pids=seen_pids if continuation else ())
        if cached_only and not items:
            return {'count':0, 'more':False, 'replenish':False}
        batch_id = secrets.token_hex(16)
        db.add(
            models.PixivRecommendationBatch(
                id=batch_id, account_revision=revision, mode=mode, items=items, profile=profile
            )
        )
        old_query = db.query(models.PixivRecommendationBatch.id).filter_by(account_revision=revision)
        if independent:
            old_query = old_query.filter_by(mode=mode).filter(models.PixivRecommendationBatch.profile['actor_id'].as_integer() == actor_id)
        old = (
            old_query
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
        "more": (cached_only and bool(items) or not exhausted or bool(pending_queries or pending_seeds)) if progressive else (not exhausted if platform_count else bool(warnings)),
        "replenish": mode == 'stock' and progressive and bool(pending_queries),
        "source_batch": source_batch,
    }
