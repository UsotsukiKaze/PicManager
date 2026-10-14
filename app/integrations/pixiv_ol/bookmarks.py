"""Account-bound bookmark mirror; durable intent, resumable scans, no remote IO in transactions."""

import secrets
from datetime import datetime, timedelta

from sqlalchemy import func, select, update

from ... import models
from . import service
from .provider import PixivError


def enabled(account):
    return bool(account.preferences.get("bookmark_sync"))


def sync_scope(account):
    value = account.preferences.get("bookmark_sync_scope", "both")
    return value if value in ("both", "public", "private") else "both"


def restrictions(scope):
    return ("public", "private") if scope == "both" else (scope,)


def state_for(db, account, pid):
    row = db.query(models.PixivBookmarkState).filter_by(account_revision=account.revision, pid=pid).first()
    if not row:
        row = models.PixivBookmarkState(
            account_revision=account.revision,
            pid=pid,
            visibility=account.preferences.get("bookmark_visibility", "private"),
        )
        db.add(row)
        db.flush()
    return row


def queue(db, row):
    db.flush()
    existing = db.query(models.PixivBookmarkOutbox).filter_by(state_id=row.id, version=row.version).first()
    if not existing:
        db.add(models.PixivBookmarkOutbox(state_id=row.id, version=row.version))
    elif existing.status in ("superseded", "failed", "paused"):
        existing.status, existing.attempts, existing.available_at = "queued", 0, datetime.utcnow()


def intent(db, account, actor_id, pid, desired, source="manual"):
    if actor_id != account.owner_id:
        return
    row = state_for(db, account, pid)
    # Repeated cart operations must not re-like a deliberately cleared work.
    if source == "auto_cart" and row.desired is not None:
        return
    statement = update(models.PixivBookmarkState).where(models.PixivBookmarkState.id == row.id)
    if source == "auto_cart":
        statement = statement.where(models.PixivBookmarkState.desired.is_(None))
    changed = db.execute(
        statement.values(
            desired=desired, source=source, version=models.PixivBookmarkState.version + 1, action_at=datetime.utcnow()
        ).returning(models.PixivBookmarkState.version)
    ).scalar_one_or_none()
    if changed is None:
        return
    db.refresh(row)
    db.query(models.PixivBookmarkOutbox).filter(
        models.PixivBookmarkOutbox.state_id == row.id,
        models.PixivBookmarkOutbox.version < row.version,
        models.PixivBookmarkOutbox.status.in_(("queued", "retry", "paused", "failed")),
    ).update({"status": "superseded"})
    if enabled(account):
        queue(db, row)


def local_feedback(db, account, pid, liked):
    row = (
        db.query(models.PixivFeedback)
        .filter_by(account_revision=account.revision, actor_id=account.owner_id, pid=pid)
        .first()
    )
    if liked:
        if row and row.value == "dislike":
            return
        if not row:
            row = models.PixivFeedback(account_revision=account.revision, actor_id=account.owner_id, pid=pid)
            db.add(row)
        row.value = "like"
    elif row and row.value == "like":
        db.delete(row)


def detail(provider, pid):
    result = provider.call("illust_bookmark_detail", illust_id=pid).get("bookmark_detail")
    if not isinstance(result, dict) or type(result.get("is_bookmarked")) is not bool:
        raise PixivError("bookmark_state_unknown")
    return result


def status(db, account):
    query = (
        db.query(models.PixivBookmarkOutbox)
        .join(models.PixivBookmarkState, models.PixivBookmarkOutbox.state_id == models.PixivBookmarkState.id)
        .filter(
            models.PixivBookmarkState.account_revision == account.revision,
            models.PixivBookmarkOutbox.version == models.PixivBookmarkState.version,
        )
    )
    scan = account.sync_state.get("bookmarks", {})
    counts = dict(
        db.query(models.PixivBookmarkState.visibility, func.count(models.PixivBookmarkState.id))
        .filter(
            models.PixivBookmarkState.account_revision == account.revision,
            models.PixivBookmarkState.observed.is_(True),
        )
        .group_by(models.PixivBookmarkState.visibility)
        .all()
    )
    return {
        "enabled": enabled(account),
        "scope": sync_scope(account),
        "visibility": account.preferences.get("bookmark_visibility", "private"),
        "public_count": counts.get("public", 0),
        "private_count": counts.get("private", 0),
        "pending": query.filter(
            models.PixivBookmarkOutbox.status.in_(("queued", "retry", "running", "paused"))
        ).count(),
        "failed": query.filter(models.PixivBookmarkOutbox.status == "failed").count(),
        "last_success": scan.get("last_success"),
        "last_full": scan.get("last_full"),
        "initial_complete": bool(scan.get("initial_complete")),
        "scanning": bool(scan.get("scan")),
        "scan_side": (scan.get("scan") or {}).get("restrict"),
        "scanned_count": (scan.get("scan") or {}).get("count", 0),
        "error": scan.get("error"),
        "local_count": db.query(models.PixivFeedback)
        .filter_by(account_revision=account.revision, actor_id=account.owner_id, value="like")
        .count(),
        "remote_count": scan.get("remote_count"),
    }


def scan_step(provider, revision, actor_id, *, full=False):
    with service.get_db_context() as db:
        account = service.require_account(db, revision)
        if not enabled(account) or actor_id != account.owner_id:
            return {"count": 0}
        user_id = account.user_id
        current = dict(account.sync_state.get("bookmarks", {}))
        scan = current.get("scan")
        scope = sync_scope(account)
        # A scope change starts a complete scan; never continue a cursor from
        # another selection or infer removals from its partial results.
        if scan and scan.get("scope", "both") != scope:
            scan = None
            full = True
        if not scan:
            initial = not current.get("initial_complete")
            requested = current.pop("full_requested", False)
            full = (
                full
                or requested
                or initial
                or current.get("completed_scope", "both") != scope
                or not current.get("last_full")
                or (datetime.utcnow() - service.iso_date(current["last_full"])).total_seconds() >= 86400
            )
            scan = {
                "marker": secrets.token_hex(16),
                "scope": scope,
                "restrict": restrictions(scope)[0],
                "cursor": {},
                "pages": 0,
                "count": 0,
                "full": full,
                "initial": initial,
                "confirm": [],
            }
            for feedback in (
                db.query(models.PixivFeedback)
                .filter_by(account_revision=revision, actor_id=actor_id, value="like")
                .all()
            ):
                row = state_for(db, account, feedback.pid)
                if row.desired is None:
                    row.desired = True
            account.sync_state = {**account.sync_state, "bookmarks": {**current, "scan": scan}}
    # Final deletion verification is paged too, so a large history cannot block browsing.
    if scan["restrict"] == "confirm":
        remaining = list(scan["confirm"])
        for pid in remaining[:3]:
            try:
                remote = detail(provider, pid)
            except PixivError as exc:
                # Unavailable works and unknown states are never interpreted as removals.
                if exc.code not in ("artwork_unavailable", "access_denied", "access_deny", "bookmark_state_unknown"):
                    raise
                remaining.remove(pid)
                continue
            with service.get_db_context() as db:
                account = service.require_account(db, revision)
                row = state_for(db, account, pid)
                if not enabled(account) or sync_scope(account) != scope:
                    return {"count": 0, "bookmark_more": enabled(account)}
                if row.visibility not in restrictions(scope):
                    remaining.remove(pid)
                    continue
                if row.version == row.synced_version and remote["is_bookmarked"] is False:
                    row.desired = row.observed = row.common = False
                    local_feedback(db, account, pid, False)
                row.checked_at = datetime.utcnow()
            remaining.remove(pid)
        scan = {**scan, "confirm": remaining}
        done = not remaining
    else:
        response = provider.call("user_bookmarks_illust", user_id=user_id, restrict=scan["restrict"], **scan["cursor"])
        raws = response.get("illusts")
        if not isinstance(raws, list):
            raise PixivError("bookmark_scan_invalid")
        next_cursor = provider.cursor(response.get("next_url"))
        if response.get("next_url") and not next_cursor:
            raise PixivError("bookmark_cursor_invalid")
        if next_cursor and next_cursor == scan["cursor"]:
            raise PixivError("bookmark_cursor_stalled")
        service.save_artworks(revision, raws, "bookmarks", actor_id)
        with service.get_db_context() as db:
            account = service.require_account(db, revision)
            if not enabled(account) or sync_scope(account) != scope:
                return {"count": 0, "bookmark_more": enabled(account)}
            for art in raws:
                pid = str(art.get("id", ""))
                if not pid.isdigit():
                    continue
                row = state_for(db, account, pid)
                row.observed, row.visibility = True, scan["restrict"]
                row.scan_marker, row.missing_scans = scan["marker"], 0
                row.checked_at = datetime.utcnow()
                if row.version == row.synced_version:
                    row.desired = row.common = True
                    if row.source == "legacy_unknown":
                        row.source = "remote"
                    local_feedback(db, account, pid, True)
        scan = {**scan, "count": scan["count"] + len(raws), "pages": scan["pages"] + 1}
        side_done = not next_cursor or (not scan["full"] and scan["pages"] >= 2)
        done = False
        if not side_done:
            scan["cursor"] = next_cursor
        elif scan["restrict"] == "public" and scope == "both":
            scan.update(restrict="private", cursor={}, pages=0)
        else:
            with service.get_db_context() as db:
                account = service.require_account(db, revision)
                confirmations = []
                if scan["full"]:
                    for row in db.query(models.PixivBookmarkState).filter_by(account_revision=revision).all():
                        if row.scan_marker == scan["marker"]:
                            continue
                        if row.observed is True and row.visibility not in restrictions(scope):
                            continue
                        if scan["initial"] and row.desired:
                            row.version += 1
                            queue(db, row)
                        elif row.common is True and row.version == row.synced_version:
                            row.missing_scans += 1
                            if row.missing_scans >= 2:
                                confirmations.append(row.pid)
                scan.update(restrict="confirm", confirm=confirmations)
                done = not confirmations
    with service.get_db_context() as db:
        account = service.require_account(db, revision)
        if not enabled(account) or sync_scope(account) != scope:
            return {"count": 0, "bookmark_more": enabled(account)}
        current = dict(account.sync_state.get("bookmarks", {}))
        if done:
            stamp = datetime.utcnow().isoformat()
            current.update(scan=None, last_success=stamp, error=None)
            if scan["full"]:
                current.update(
                    last_full=stamp, initial_complete=True, remote_count=scan["count"], completed_scope=scope
                )
        else:
            current.update(scan=scan, error=None)
        account.sync_state = {**account.sync_state, "bookmarks": current}
        more = not done or current.get("full_requested", False)
    return {"count": scan["count"], "bookmark_more": more}


def run_outbox_once():
    now = datetime.utcnow()
    with service.get_db_context() as db:
        account = db.get(models.PixivAccount, 1)
        if (
            not account
            or account.status != "connected"
            or not enabled(account)
            or not account.sync_state.get("bookmarks", {}).get("initial_complete")
        ):
            return False
        db.query(models.PixivBookmarkOutbox).filter(
            models.PixivBookmarkOutbox.status == "running", models.PixivBookmarkOutbox.lease_until < now
        ).update({"status": "retry"})
        candidate = (
            select(models.PixivBookmarkOutbox.id)
            .join(models.PixivBookmarkState)
            .where(
                models.PixivBookmarkState.account_revision == account.revision,
                models.PixivBookmarkOutbox.status.in_(("queued", "retry")),
                models.PixivBookmarkOutbox.available_at <= now,
            )
            .order_by(models.PixivBookmarkOutbox.id)
            .limit(1)
            .scalar_subquery()
        )
        task_id = db.execute(
            update(models.PixivBookmarkOutbox)
            .where(
                models.PixivBookmarkOutbox.id == candidate, models.PixivBookmarkOutbox.status.in_(("queued", "retry"))
            )
            .values(
                status="running",
                lease_until=now + timedelta(minutes=5),
                attempts=models.PixivBookmarkOutbox.attempts + 1,
            )
            .returning(models.PixivBookmarkOutbox.id)
        ).scalar_one_or_none()
        if not task_id:
            return False
        task = db.get(models.PixivBookmarkOutbox, task_id)
        row = db.get(models.PixivBookmarkState, task.state_id)
        if task.version != row.version:
            task.status = "superseded"
            return True
        pid, desired, visibility, version, state_id = row.pid, row.desired, row.visibility, row.version, row.id
        actor_id, revision = account.owner_id, account.revision
    provider = None
    try:
        provider = service.client_for_job(actor_id, revision)
        remote = detail(provider, pid)
        # A concurrent UI operation can supersede a queued request during authentication.
        with service.get_db_context() as db:
            account = service.require_account(db, revision)
            row = db.get(models.PixivBookmarkState, state_id)
            if row.version != version or not enabled(account):
                db.get(models.PixivBookmarkOutbox, task_id).status = "superseded"
                return True
        if remote["is_bookmarked"] != desired:
            if desired:
                provider.call("illust_bookmark_add", illust_id=pid, restrict=visibility)
            else:
                provider.call("illust_bookmark_delete", illust_id=pid)
            remote = detail(provider, pid)
        if remote["is_bookmarked"] != desired:
            raise PixivError("bookmark_not_confirmed")
        with service.get_db_context() as db:
            service.require_account(db, revision)
            row = db.get(models.PixivBookmarkState, state_id)
            task = db.get(models.PixivBookmarkOutbox, task_id)
            task.status, task.error = "completed", None
            if row.version == version:
                row.observed = row.common = desired
                row.synced_version, row.checked_at = version, datetime.utcnow()
                if desired:
                    row.visibility = "private" if remote.get("restrict") == "private" else "public"
    except Exception as exc:
        code = exc.code if isinstance(exc, PixivError) else "bookmark_processing_failed"
        with service.get_db_context() as db:
            task = db.get(models.PixivBookmarkOutbox, task_id)
            task.error = code
            task.status = (
                "paused"
                if code == "reauth_required"
                else ("failed" if task.attempts >= 8 or code in ("account_changed", "permission_revoked") else "retry")
            )
            task.available_at = datetime.utcnow() + timedelta(
                seconds=max(
                    getattr(exc, "delay", 0), (5, 30, 120, 600)[min(task.attempts - 1, 3)] + secrets.randbelow(5)
                )
            )
            account = db.get(models.PixivAccount, 1)
            if account and account.revision == revision and code == "reauth_required":
                account.status = "reauth_required"
    finally:
        if provider:
            provider.close()
    return True
