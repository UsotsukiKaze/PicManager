"""Library Pixiv identity and artist metadata, independent of manual tag management."""

import re
from datetime import datetime
from sqlalchemy import func, or_

from . import models

PID = re.compile(r"^([0-9]{1,30})(?:_p([0-9]{1,4}))?$", re.ASCII)


def split_pid(value):
    match = PID.fullmatch(str(value or "").strip())
    return (match[1], int(match[2]) if match[2] is not None else None) if match else None


def canonical_pid(work_id, page):
    if not str(work_id).isascii() or not str(work_id).isdigit() or not 0 <= page < 1000:
        raise ValueError("无效的 Pixiv 页码")
    return f"{work_id}_p{page}"


def normalize_new_pid(value, filename=None):
    hint = re.search(r"(?:^|[/\\])([0-9]+)_p([0-9]+)(?:[_.]|$)", str(filename or ""), re.ASCII)
    if not value and hint:
        return canonical_pid(hint[1], int(hint[2]))
    parsed = split_pid(value)
    if not parsed:
        return value
    work_id, page = parsed
    if page is None:
        page = int(hint[2]) if hint and hint[1] == work_id else 0
    return canonical_pid(work_id, page)


def library_pixiv_pages(db, work_ids=None):
    """Resolve library PIDs as well as validated/imported identities in bulk.

    Legacy bare IDs mean page zero, unless their original filename specifies a
    page. Never infer the other pages of a multi-page work from one local image.
    No image files or entity relationships are loaded for this lookup.
    """
    ids = None if work_ids is None else {
        str(value) for value in work_ids if re.fullmatch(r"[0-9]{1,30}", str(value), re.ASCII)
    }
    if ids == set():
        return {}
    pages = {}

    def add(work, page):
        if (ids is None or work in ids) and 0 <= page < 1000:
            pages.setdefault(work, set()).add(page)

    images = db.query(models.Image.pid, models.Image.original_filename).filter(models.Image.pid.isnot(None))
    sources = db.query(models.PixivImageSource.work_id, models.PixivImageSource.page_index).join(models.Image).filter(models.PixivImageSource.provider == 'pixiv')
    metadata = db.query(models.PixivImageMetadata.work_id, models.PixivImageMetadata.page_index).join(models.Image)
    if ids is not None:
        pid = func.trim(models.Image.pid)
        images = images.filter(or_(pid.in_(ids), *(pid.like(f'{work}\\_p%', escape='\\') for work in ids)))
        sources = sources.filter(models.PixivImageSource.work_id.in_(ids))
        metadata = metadata.filter(models.PixivImageMetadata.work_id.in_(ids))
    for pid, filename in images:
        try:
            parsed = split_pid(normalize_new_pid(pid, filename))
        except ValueError:
            continue
        if parsed:
            add(parsed[0], parsed[1] if parsed[1] is not None else 0)
    for work, page in sources:
        add(work, page)
    for work, page in metadata:
        add(work, page)
    return pages


def library_pixiv_image(db, work_id, page):
    """Return the existing image for an import, including pre-Pixiv-ol PIDs."""
    source = db.query(models.PixivImageSource).filter_by(provider='pixiv', work_id=work_id, page_index=page).first()
    if source:
        return source.image
    pid = func.trim(models.Image.pid)
    candidates = db.query(models.Image).filter(or_(pid == work_id, pid.like(f'{work_id}\\_p%', escape='\\'))).order_by(models.Image.image_id)
    for image in candidates:
        try:
            parsed = split_pid(normalize_new_pid(image.pid, image.original_filename))
        except ValueError:
            continue
        if parsed == (work_id, page):
            return image
    return db.query(models.Image).join(models.PixivImageMetadata).filter(models.PixivImageMetadata.work_id == work_id, models.PixivImageMetadata.page_index == page).first()


def apply_metadata(db, image, art, page, *, apply_tag_matches=False):
    """Preserve page-specific manual labels; work tags are mapping suggestions."""
    if not 0 <= page < int(art["page_count"]):
        raise ValueError("页码不属于该作品")
    artist_id = str(art.get("author_id") or "")
    if not artist_id.isascii() or not artist_id.isdigit() or int(artist_id) <= 0:
        raise ValueError("画师信息无效")
    artist = next(
        (row for row in db.new if isinstance(row, models.PixivArtist) and row.id == artist_id), None
    ) or db.get(models.PixivArtist, artist_id)
    if artist is None:
        artist = models.PixivArtist(id=artist_id, name=str(art.get("author") or "")[:255])
        db.add(artist)
    artist.name = str(art.get("author") or "")[:255]
    metadata = image.pixiv_metadata
    if metadata is None:
        metadata = models.PixivImageMetadata(image=image)
        db.add(metadata)
    metadata.artist = artist
    metadata.work_id, metadata.page_index = art["pid"], page
    metadata.page_count, metadata.tags = int(art["page_count"]), art.get("tags", [])
    metadata.validated_at = datetime.utcnow()
    metadata.status = "verified"
    from .tag_mappings import check_image_tags
    check_image_tags(db, image, art, apply_matches=apply_tag_matches)
    image.pid = canonical_pid(art["pid"], page)
    image.pixiv_checked_at = datetime.utcnow()
    if art.get("x_restrict"):
        image.age_rating = "r18"
    ensure_source_tag(db, image)
    return metadata


def ensure_source_tag(db, image):
    source_tag = (
        next((row for row in db.new if isinstance(row, models.FeatureTag) and row.name.lower() == "pixiv"), None)
        or db.query(models.FeatureTag).filter(func.lower(models.FeatureTag.name) == "pixiv").first()
    )
    if source_tag is None:
        source_tag = models.FeatureTag(name="Pixiv")
        db.add(source_tag)
    if source_tag not in image.feature_tags:
        image.feature_tags.append(source_tag)


def backfill_checked_tags(db):
    """Repair legacy checked records from local snapshots, without rematching roles.

    Preserve confirmed page-specific tags, identity and validation dates. Missing
    snapshots stay untouched and never trigger another remote tag comparison.
    """
    from sqlalchemy.orm import selectinload

    rows = db.query(models.Image).filter(
        models.Image.pixiv_checked_at.isnot(None),
        or_(
            ~models.Image.feature_tags.any(func.lower(models.FeatureTag.name) == "pixiv"),
            ~models.Image.pixiv_metadata.has(),
            models.Image.pixiv_metadata.has(models.PixivImageMetadata.tags == []),
        ),
    ).options(selectinload(models.Image.pixiv_metadata), selectinload(models.Image.pixiv_sources), selectinload(models.Image.feature_tags)).all()
    identities = {}
    for image in rows:
        meta = image.pixiv_metadata
        if meta and meta.status != "verified":
            continue
        try:
            parsed = split_pid(normalize_new_pid(image.pid, image.original_filename)) if split_pid(image.pid) else None
        except ValueError:
            continue
        if meta:
            parsed = (meta.work_id, meta.page_index)
        if parsed:
            identities[image.image_id] = parsed
    work_ids = {work for work, _ in identities.values()}
    snapshots = {}
    for start in range(0, len(work_ids), 500):
        chunk = sorted(work_ids)[start:start + 500]
        for row in db.query(models.PixivArtwork).filter(models.PixivArtwork.pid.in_(chunk)).order_by(models.PixivArtwork.fetched_at, models.PixivArtwork.id):
            snapshots[row.pid] = row.metadata_json
    repaired = 0
    for image in rows:
        identity = identities.get(image.image_id)
        if not identity:
            continue
        work, page = identity
        meta = image.pixiv_metadata
        confirmed_source = next((source for source in image.pixiv_sources if source.provider == "pixiv" and source.work_id == work and source.page_index == page), None)
        art = (confirmed_source.metadata_json if confirmed_source and confirmed_source.metadata_json.get("tags") else None) or snapshots.get(work)
        changed = False
        if meta is None and art and (int(art.get("page_count") or 0) == 1 or confirmed_source) and str(art.get("pid")) == work and 0 <= page < int(art.get("page_count") or 0):
            checked_at, pid, rating = image.pixiv_checked_at, image.pid, image.age_rating
            apply_metadata(db, image, art, page, apply_tag_matches=False)
            image.pixiv_checked_at, image.pid, image.age_rating = checked_at, pid, rating
            image.pixiv_metadata.validated_at = checked_at
            changed = True
        elif meta and not meta.tags and art and str(art.get("pid")) == work and art.get("tags"):
            meta.tags = art["tags"]
            changed = True
        if image.pixiv_metadata and not any(tag.name.lower() == "pixiv" for tag in image.feature_tags):
            ensure_source_tag(db, image)
            changed = True
        repaired += bool(changed)
    return repaired


def public_metadata(image):
    meta = image.pixiv_metadata
    return {
        "artist": (
            {"id": meta.artist.id, "name": meta.artist.name, "url": f"https://www.pixiv.net/users/{meta.artist.id}"}
            if meta and meta.artist
            else None
        ),
        "pixiv_tags": meta.tags if meta else [],
        "pixiv_verified": bool(image.pixiv_checked_at and (not meta or meta.status == "verified")),
        "local_verified": bool(image.local_checked_at),
        "pixiv_page": meta.page_index if meta else None,
        "pixiv_page_count": meta.page_count if meta else None,
    }
