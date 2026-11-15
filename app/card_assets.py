"""Shared card cache and bounded, resumable library derivative maintenance."""
import hashlib
import json
import logging
import sqlite3
import threading
import time
from pathlib import Path
from urllib.parse import unquote, urlsplit

from PIL import Image
from .config import settings
from . import card_art
from .artist_avatars import avatar_path, cache_avatar

log = logging.getLogger(__name__)
_stop = threading.Event()
_thread = None
_locks = [threading.Lock() for _ in range(128)]
_render_slots = threading.BoundedSemaphore(2)
_busy = 0
_busy_lock = threading.Lock()
_prune_lock = threading.Lock()
_last_prune = 0


def root():
    p = Path(settings.DATA_PATH) / 'card-assets'
    p.mkdir(parents=True, exist_ok=True)
    return p


def connect():
    db = sqlite3.connect(root() / 'maintenance.sqlite3', timeout=10)
    db.execute('CREATE TABLE IF NOT EXISTS tasks (key TEXT PRIMARY KEY, kind TEXT, subject TEXT, revision TEXT, payload TEXT, status TEXT, attempts INTEGER DEFAULT 0, next REAL DEFAULT 0, error TEXT)')
    return db


def enqueue(kind, subject, revision, payload):
    key = hashlib.sha256(f'{kind}|{subject}|{revision}'.encode()).hexdigest()
    with connect() as db:
        db.execute('INSERT OR IGNORE INTO tasks(key,kind,subject,revision,payload,status) VALUES(?,?,?,?,?,?)',
                   (key, kind, subject, revision, json.dumps(payload), 'queued'))
        db.execute("UPDATE tasks SET status='queued',attempts=0 WHERE key=? AND status='completed'", (key,))


def valid_avatar(uid):
    p = avatar_path(uid)
    try:
        with Image.open(p) as im:
            im.verify()
        return p
    except (OSError, ValueError):
        return None


def queue_avatar(uid):
    from .database import get_db_context
    from . import models
    if not uid or valid_avatar(uid):
        return
    with connect() as db:
        if db.execute("SELECT 1 FROM tasks WHERE kind='avatar' AND subject=? AND status IN ('queued','retry','failed') LIMIT 1", (uid,)).fetchone():
            return
    with get_db_context() as db:
        rows = db.query(models.PixivImageSource).filter(
            models.PixivImageSource.metadata_json['author_id'].as_string() == uid).all()
        arts = [r.metadata_json for r in rows]
        arts += [r.metadata_json for r in db.query(models.PixivArtwork).filter_by(author_id=uid).order_by(models.PixivArtwork.fetched_at.desc()).all()]
    art = next((a for a in arts if a and a.get('author_avatar')), None)
    if art:
        enqueue('avatar', uid, hashlib.sha256(art['author_avatar'].encode()).hexdigest(), art)


def preview_ready(source, target, width, height):
    try:
        if target.stat().st_mtime_ns < source.stat().st_mtime_ns:
            return False
        with Image.open(target) as im:
            scale = min(1, 896 / width, 1280 / height)
            return im.width >= int(width * scale) and im.height >= int(height * scale) and abs(im.width / im.height / (width / height) - 1) <= .01
    except (OSError, ValueError, TypeError, ZeroDivisionError):
        return False


def inventory():
    from .database import get_db_context
    from . import models
    from .services import ImageService
    with get_db_context() as db:
        rows = db.query(models.Image).filter_by(file_status='available').all()
        uids = set()
        for row in rows:
            if _stop.is_set():
                return
            source = Path(ImageService.image_full_path(row))
            target = Path(settings.PREVIEW_PATH) / (row.image_id + '.webp')
            if source.is_file() and not preview_ready(source, target, row.width, row.height):
                enqueue('preview', row.image_id, card_art.revision(source), {'source': str(source), 'target': str(target), 'width': row.width, 'height': row.height})
            if row.pixiv_metadata and row.pixiv_metadata.artist_id:
                uids.add(row.pixiv_metadata.artist_id)
        arts = {}
        for (art,) in db.query(models.PixivImageSource.metadata_json).filter_by(provider='pixiv').all():
            if art and art.get('author_avatar') and str(art.get('author_id')) in uids:
                arts[str(art['author_id'])] = art
        for row in db.query(models.PixivArtwork).filter(models.PixivArtwork.author_id.in_(uids)).order_by(models.PixivArtwork.fetched_at).all():
            if row.metadata_json and row.metadata_json.get('author_avatar'):
                arts[row.author_id] = row.metadata_json
    for uid in uids:
        if _stop.is_set():
            return
        art = arts.get(uid)
        if not valid_avatar(uid) and art:
            enqueue('avatar', uid, hashlib.sha256(art['author_avatar'].encode()).hexdigest(), art)


def work():
    from .services import ImageService
    import os
    if os.name == 'nt':
        import ctypes
        ctypes.windll.kernel32.SetThreadPriority(ctypes.windll.kernel32.GetCurrentThread(), -1)
    try:
        inventory()
    except Exception:
        log.exception('Card asset inventory failed')
    turn = 0
    while not _stop.is_set():
        with _busy_lock:
            busy = _busy
        if busy:
            _stop.wait(1)
            continue
        with connect() as db:
            preferred = 'preview' if turn % 3 == 0 else 'avatar'
            row = db.execute("SELECT key,kind,subject,revision,payload,attempts FROM tasks WHERE status IN ('queued','retry') AND next<=? ORDER BY CASE WHEN kind=? THEN 0 ELSE 1 END,rowid LIMIT 1", (time.time(), preferred)).fetchone()
            turn += 1
        if not row:
            _stop.wait(10)
            continue
        key, kind, subject, revision, payload, attempts = row
        try:
            data = json.loads(payload)
            if kind == 'avatar':
                if not valid_avatar(subject):
                    avatar_path(subject).unlink(missing_ok=True)
                    if not cache_avatar(data):
                        raise ValueError('No usable avatar URL')
            else:
                source, target = Path(data['source']), Path(data['target'])
                if card_art.revision(source) == revision and not preview_ready(source, target, data.get('width'), data.get('height')):
                    ImageService.write_preview(str(source), str(target))
                from .database import get_db_context
                from . import models
                with get_db_context() as db:
                    image = db.get(models.Image, subject)
                    if image and target.is_file():
                        image.preview_status = 'ready'
            with connect() as db:
                db.execute("UPDATE tasks SET status='completed',error=NULL WHERE key=?", (key,))
        except Exception as exc:
            attempts += 1
            with connect() as db:
                db.execute('UPDATE tasks SET status=?,attempts=?,next=?,error=? WHERE key=?',
                           ('failed' if attempts >= 5 else 'retry', attempts, time.time() + min(3600, 60 * 2 ** attempts), str(exc)[:500], key))
            log.warning('Card asset %s %s failed: %s', kind, subject, exc)
        _stop.wait(.5)


def start():
    global _thread
    if _thread and _thread.is_alive():
        return
    _stop.clear()
    _thread = threading.Thread(target=work, name='card-assets', daemon=True)
    _thread.start()


def stop():
    _stop.set()
    if _thread:
        _thread.join(timeout=5)


def local_resource(url):
    path = unquote(urlsplit(url or '').path)
    base = Path(settings.RESOURCE_PATH).resolve()
    if not path.startswith('/resource/'):
        return None
    target = (base / path[len('/resource/'):]).resolve()
    if base not in target.parents or not target.is_file():
        return None
    return target


def file_version(path):
    return card_art.revision(path) if path and path.is_file() else None


def prune():
    global _last_prune
    with _prune_lock:
        if time.monotonic() - _last_prune < 60:
            return
        _last_prune = time.monotonic()
        files = sorted((p.stat().st_mtime, p.stat().st_size, p) for p in root().glob('*.jpg'))
        total = sum(s for _, s, _ in files)
        for _, size, path in files:
            if total <= 2 * 1024**3:
                break
            path.unlink(missing_ok=True)
            total -= size


def render(info, theme):
    global _busy
    from .card_renderer import render_card
    from .database import get_db_context
    from . import models
    from .services import ImageService
    with get_db_context() as db:
        row = db.get(models.Image, info['image_id'])
        source = Path(ImageService.image_full_path(row))
        preview = Path(settings.PREVIEW_PATH) / (row.image_id + '.webp')
        width, height = row.width, row.height
    uid = str((info.get('artist') or {}).get('id') or '')
    artist = avatar_path(uid) if uid and uid.isascii() and uid.isdigit() else None
    if artist and not artist.is_file():
        artist = None
        queue_avatar(uid)
    chars = info.get('characters') or []
    character = local_resource(chars[0].get('avatar_url')) if chars else None
    stable = {k: v for k, v in info.items() if k not in ('image_url', 'original_image_url')}
    stable.update(theme=theme, artist_version=file_version(artist), character_version=file_version(character), template='v1')
    key = hashlib.sha256(json.dumps(stable, sort_keys=True, default=str).encode()).hexdigest()
    target = root() / (key + '.jpg')
    with _busy_lock:
        _busy += 1
    try:
        with _locks[int(key[:4], 16) % len(_locks)]:
            if target.is_file():
                target.touch()
                return target.read_bytes(), True
            with _render_slots:
                if preview_ready(source, preview, width, height):
                    art = preview.read_bytes()
                else:
                    enqueue('preview', info['image_id'], card_art.revision(source), {'source': str(source), 'target': str(preview), 'width': width, 'height': height})
                    art = card_art.artwork(source)
                payload = render_card(info, art, artist_avatar=artist.read_bytes() if artist else None,
                                      character_avatar=character.read_bytes() if character else None, theme=theme)
                stage = target.with_suffix('.part')
                stage.write_bytes(payload)
                stage.replace(target)
            prune()
            return payload, False
    finally:
        with _busy_lock:
            _busy -= 1
