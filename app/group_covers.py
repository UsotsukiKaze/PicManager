"""Homepage covers use local R12 landscape images and cached Pixiv popularity.

Only library media is published. Remote metadata is refreshed by the existing
account worker, outside homepage requests and database transactions.
"""
from datetime import datetime, timedelta
from itertools import zip_longest

from sqlalchemy import or_

from . import models
from .pixiv_metadata import split_pid

REFRESH_AFTER = timedelta(hours=24)
CANDIDATES_PER_GROUP = 12
REQUESTS_PER_JOB = 12


def _bookmarks(metadata):
    value = (metadata or {}).get("bookmarks")
    return value if type(value) is int and value >= 0 else None


def candidates(db, group_id):
    rows = (
        db.query(models.Image.image_id, models.Image.pid, models.Image.width, models.Image.height,
                 models.PixivImageMetadata.work_id, models.Image.preview_status, models.Image.thumb_status)
        .outerjoin(models.PixivImageMetadata, models.PixivImageMetadata.image_id == models.Image.image_id)
        .filter(models.Image.file_status == "available", models.Image.age_rating == "r12",
                models.Image.height > 0, models.Image.width > models.Image.height,
                or_(models.Image.groups.any(models.Group.id == group_id),
                    models.Image.characters.any(models.Character.group_id == group_id)))
        .all()
    )
    result = []
    for image_id, pid, width, height, work_id, preview_status, thumb_status in rows:
        parsed = split_pid(pid)
        result.append({"image_id": image_id, "width": width, "height": height,
                       "pid": work_id or (parsed[0] if parsed else None),
                       "preview_url": (f"/resource/previews/{image_id}.webp" if preview_status == "ready" else
                                       f"/resource/thumbs/{image_id}.webp" if thumb_status == "ready" else None)})
    return result


def artwork_scores(db, rows):
    ids = sorted({row["pid"] for row in rows if row["pid"]})
    account = db.get(models.PixivAccount, 1)
    scores, fetched, excluded = {}, {}, set()
    for start in range(0, len(ids), 500):
        batch = ids[start:start + 500]
        # Imported artwork metadata is useful even before connecting Pixiv-ol.
        for pid, metadata in db.query(models.PixivImageSource.work_id, models.PixivImageSource.metadata_json).filter(
            models.PixivImageSource.work_id.in_(batch), models.PixivImageSource.provider == "pixiv"
        ):
            if metadata.get("x_restrict") in (1, 2):
                excluded.add(pid)
                continue
            score = _bookmarks(metadata)
            if score is not None and metadata.get("x_restrict") == 0:
                scores[pid] = max(scores.get(pid, -1), score)
        if not account:
            continue
        for art in db.query(models.PixivArtwork).filter(
            models.PixivArtwork.account_revision == account.revision, models.PixivArtwork.pid.in_(batch)
        ):
            if art.metadata_json.get("x_restrict") != 0:
                excluded.add(art.pid)
                continue
            score = _bookmarks(art.metadata_json)
            if score is not None:
                scores[art.pid] = score
                fetched[art.pid] = art.fetched_at
    return scores, fetched, excluded


def choose_cover(rows, scores, excluded=()):
    eligible = [row for row in rows if row["pid"] not in excluded and row["preview_url"]]
    if not eligible:
        return None
    winner = max(eligible, key=lambda row: (
        scores.get(row["pid"], -1), -abs(row["width"] / row["height"] - 16 / 9),
        row["width"] * row["height"], row["image_id"]
    ))
    score = scores.get(winner["pid"])
    return {"image_id": winner["image_id"], "preview_url": winner["preview_url"],
            "width": winner["width"], "height": winner["height"],
            "source": "pixiv_bookmarks" if score is not None else "local", "bookmarks": score}


def attach_covers(db, groups):
    """Return immediate local covers and deduplicate bounded metadata refreshes."""
    pools = {group["id"]: candidates(db, group["id"]) for group in groups}
    rows = [row for pool in pools.values() for row in pool]
    scores, fetched, excluded = artwork_scores(db, rows)
    for group in groups:
        group["cover"] = choose_cover(pools[group["id"]], scores, excluded)
        group["cover_refreshing"] = False
    account = db.get(models.PixivAccount, 1)
    owner = db.get(models.User, account.owner_id) if account else None
    if not account or account.status != "connected" or not owner or owner.role not in ("root", "admin"):
        return groups
    now = datetime.utcnow()
    from .integrations.pixiv_ol.jobs import enqueue, ACTIVE
    active = db.query(models.PixivJob).filter(models.PixivJob.kind == "home_covers",
        models.PixivJob.account_revision == account.revision, models.PixivJob.status.in_(ACTIVE)).first()
    if active:
        for group in groups:
            group["cover_refreshing"] = True
        return groups
    attempts = dict(account.sync_state.get("home_cover_attempts", {}))
    pending = []
    for pool in pools.values():
        ordered = sorted(pool, key=lambda row: (scores.get(row["pid"], -1),
                         -abs(row["width"] / row["height"] - 16 / 9)), reverse=True)
        ids = list(dict.fromkeys(row["pid"] for row in ordered if row["pid"] and row["pid"] not in excluded))[:CANDIDATES_PER_GROUP]
        due = []
        for pid in ids:
            last = fetched.get(pid)
            try:
                attempted = datetime.fromisoformat(attempts.get(pid, "1970-01-01"))
            except (ValueError, TypeError):
                attempted = datetime(1970, 1, 1)
            if (last is None or now - last >= REFRESH_AFTER) and now - attempted >= REFRESH_AFTER:
                due.append(pid)
        pending.append(due)
    # Round-robin avoids one large group consuming the entire request budget.
    ids = list(dict.fromkeys(pid for batch in zip_longest(*pending) for pid in batch if pid))[:REQUESTS_PER_JOB]
    if ids:
        enqueue(db, account.owner_id, "home_covers", {"pids": ids})
        attempts.update({pid: now.isoformat() for pid in ids})
        attempts = dict(sorted(attempts.items(), key=lambda item: item[1], reverse=True)[:2000])
        account.sync_state = {**account.sync_state, "home_cover_attempts": attempts}
        for group in groups:
            group["cover_refreshing"] = True
    return groups


def refresh_scores(provider, revision, actor_id, pids):
    from .integrations.pixiv_ol import service
    from .integrations.pixiv_ol.provider import PixivError
    count = 0
    for pid in list(dict.fromkeys(pids))[:REQUESTS_PER_JOB]:
        if not str(pid).isascii() or not str(pid).isdigit():
            continue
        try:
            raw = provider.call("illust_detail", illust_id=pid).get("illust")
        except PixivError as exc:
            if exc.code in {"artwork_unavailable", "access_deny", "access_denied"}:
                continue
            raise
        if not raw or str(raw.get("id")) != pid:
            continue
        service.save_artworks(revision, [raw], "home_cover", actor_id)
        count += 1
    return {"count": count}
