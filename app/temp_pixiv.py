"""Cancellable temp preflight. Suggestions never alter files or manual labels."""

import copy
import re
import secrets
import threading
import time
from collections import OrderedDict
from pathlib import Path
from urllib.parse import unquote
from datetime import datetime, timedelta

from PIL import Image

from . import models
from .config import settings
from .database import get_db_context
from .integrations.pixiv_ol import service, viewer
from .integrations.pixiv_ol.provider import PixivError
from .pixiv_metadata import canonical_pid, split_pid, apply_metadata
from .services import ImageService

LOCK = threading.RLock()
SLOTS = threading.BoundedSemaphore(2)
RUNS = {}
RESULTS = OrderedDict()
LEASE_SECONDS = 90
CACHE_SECONDS = 1800


def safe_path(filename):
    if not filename or any(char in filename for char in ('/', '\\', '\x00')):
        raise PixivError('invalid_temp_file')
    root = Path(settings.TEMP_PATH).resolve()
    path = (root / filename).resolve()
    allowed = {str(extension).lower().lstrip('.') for extension in settings.ALLOWED_EXTENSIONS}
    if not path.is_relative_to(root) or not path.is_file() or path.suffix.lower().lstrip('.') not in allowed:
        raise PixivError('temp_file_changed')
    return path


def files():
    allowed = {str(extension).lower().lstrip('.') for extension in settings.ALLOWED_EXTENSIONS}
    items = []
    root = Path(settings.TEMP_PATH).resolve()
    if root.is_dir():
        for path in sorted(root.iterdir(), key=lambda item: item.name.casefold()):
            if path.is_file() and path.suffix.lower().lstrip('.') in allowed and path.resolve().is_relative_to(root):
                items.append({'filename': path.name, 'display_name': path.name})
    return items


def snapshot(path):
    stat = path.stat()
    return (str(path), stat.st_size, stat.st_mtime_ns)


def hint(text):
    text = unquote(str(text or '')[:32768])
    page = re.search(r'(?<!\d)([1-9]\d{4,11})_p(\d{1,3})(?=[_.\s\-]|$)', text, re.ASCII)
    if page:
        return page[1], int(page[2])
    link = re.search(r'(?:pixiv\.net/(?:[a-z]{2}/)?artworks/|pixiv\.net/member_illust\.php\?[^\s]*illust_id=)([1-9]\d{4,11})(?!\d)', text, re.ASCII)
    if link:
        return link[1], None
    bare = re.fullmatch(r'([1-9]\d{4,11})\.[a-zA-Z]{2,5}', text, re.ASCII)
    return (bare[1], None) if bare else None


def identify(path):
    identified = hint(path.name)
    if identified:
        return identified
    # Header metadata only; no OCR or full-resolution feature extraction.
    with Image.open(path) as image:
        texts = [value for value in image.info.values() if isinstance(value, str)]
        texts.extend(value for value in image.getexif().values() if isinstance(value, str))
        for value in texts[:32]:
            identified = hint(value)
            if identified:
                return identified
    return None


def _close(run):
    run['stopped'] = True
    if not run['busy'] and run['client']:
        run['client'].close()
        run['client'] = None


def start(actor, owner):
    with get_db_context() as db:
        service.require_actor(db, actor)
        account = service.require_account(db)
        if account.status != 'connected':
            raise PixivError('auth_required')
        revision = account.revision
    with LOCK:
        for key, run in list(RUNS.items()):
            if run['expires'] < time.monotonic() or run['owner'] == owner:
                _close(run)
                RUNS.pop(key)
        if len(RUNS) >= 16:
            raise PixivError('temp_precheck_busy')
        run_id = secrets.token_hex(24)
        RUNS[run_id] = dict(actor=actor, owner=owner, revision=revision, client=None,
                            stopped=False, busy=False, expires=time.monotonic() + LEASE_SECONDS)
    return {'run_id': run_id}


def stop(run_id, actor, owner):
    with LOCK:
        run = RUNS.get(run_id)
        if run and (run['actor'], run['owner']) == (actor, owner):
            _close(run)
            RUNS.pop(run_id)
    return {'stopped': True}


def guard(run, path=None, before=None):
    if run['stopped'] or run['expires'] < time.monotonic():
        raise PixivError('temp_precheck_stopped')
    with get_db_context() as db:
        service.require_actor(db, run['actor'])
        service.require_account(db, run['revision'])
    if path and snapshot(path) != before:
        raise PixivError('temp_file_changed')


def public_result(result, actor):
    from .routers.integrations.pixiv_ol import public_art
    output = {key: copy.deepcopy(result[key]) for key in ('status', 'filename', 'pid', 'page', 'distance', 'token')}
    with get_db_context() as db:
        service.require_actor(db, actor)
        service.require_account(db, result['revision'])
        row = db.query(models.PixivArtwork).filter_by(account_revision=result['revision'], pid=result['art']['pid']).first()
        output['artwork'] = public_art(db, row, actor_id=actor) if row else None
    return output


def check(run_id, filename, actor, owner):
    path = safe_path(filename)
    before = snapshot(path)
    with LOCK:
        run = RUNS.get(run_id)
        if not run or (run['actor'], run['owner']) != (actor, owner) or run['stopped'] or run['expires'] < time.monotonic():
            raise PixivError('temp_precheck_stopped')
        if run['busy']:
            raise PixivError('temp_precheck_busy')
        run['busy'] = True
        run['expires'] = time.monotonic() + LEASE_SECONDS
    try:
        guard(run, path, before)
        identity = identify(path)
        if not identity:
            return {'filename': filename, 'status': 'ordinary'}
        work, page = identity
        with LOCK:
            cached = next((result for result in reversed(RESULTS.values())
                           if result['snapshot'] == before and result['revision'] == run['revision']
                           and result['actor'] == actor and result['expires'] > time.monotonic()), None)
        if cached:
            guard(run, path, before)
            return public_result(cached, actor)
        # Bounded across tabs/sessions; one sequential queue per run keeps the
        # Pixiv API client and refresh-token rotation out of concurrent use.
        if not SLOTS.acquire(timeout=1):
            raise PixivError('temp_precheck_busy')
        try:
            guard(run, path, before)
            with get_db_context() as db:
                row = db.query(models.PixivArtwork).filter_by(account_revision=run['revision'], pid=work).first()
                art = copy.deepcopy(row.metadata_json) if row and row.fetched_at > datetime.utcnow() - timedelta(hours=1) else None
            if not art:
                if run['client'] is None:
                    run['client'] = service.client_for_job(actor, run['revision'])
                guard(run, path, before)
                raw = run['client'].call('illust_detail', illust_id=work).get('illust')
                art = service.normalize_artwork(raw or {})
                if not art or art['pid'] != work:
                    raise PixivError('artwork_unsupported')
                with LOCK:
                    guard(run, path, before)
                    service.save_artworks(run['revision'], [raw], 'temp_check', actor)
            if page is None and art['page_count'] == 1:
                page = 0
            distance = None
            if page is not None and 0 <= page < art['page_count']:
                try:
                    guard(run, path, before)
                    remote, _ = viewer.clear_preview(art, run['revision'], page)
                    distance = ImageService.dhash_distance(ImageService.compute_dhash(str(path)), ImageService.compute_dhash(str(remote)))
                except (PixivError, OSError, ValueError):
                    # CDN failures and ambiguous identity remain manual reviews.
                    guard(run, path, before)
            else:
                page = None
            guard(run, path, before)
        finally:
            SLOTS.release()
        result = dict(filename=filename, art=art, revision=run['revision'], actor=actor,
                      snapshot=before, page=page, pid=canonical_pid(work, page) if page is not None else work,
                      distance=distance, status='verified' if distance is not None and distance <= settings.PIXIV_UPGRADE_DHASH_DISTANCE else 'review',
                      token=secrets.token_hex(24), expires=time.monotonic() + CACHE_SECONDS)
        with LOCK:
            guard(run, path, before)
            for key in list(RESULTS):
                if RESULTS[key]['expires'] <= time.monotonic():
                    RESULTS.pop(key)
            RESULTS[result['token']] = result
            while len(RESULTS) > 512:
                RESULTS.popitem(last=False)
        return public_result(result, actor)
    finally:
        with LOCK:
            run['busy'] = False
            if run['stopped']:
                _close(run)


def proof(db, token, filename, actor, pid, identity_confirmed=False):
    if not token:
        return None
    with LOCK:
        result = copy.deepcopy(RESULTS.get(token))
    if not result or result['actor'] != actor or result['filename'] != filename or result['expires'] <= time.monotonic():
        raise PixivError('temp_precheck_expired')
    service.require_account(db, result['revision'])
    if snapshot(safe_path(filename)) != result['snapshot']:
        raise PixivError('temp_file_changed')
    parsed = split_pid(pid)
    if not parsed or parsed[0] != result['art']['pid'] or parsed[1] is None or parsed[1] >= result['art']['page_count']:
        raise PixivError('invalid_page')
    if (result['status'] != 'verified' or parsed[1] != result['page']) and not identity_confirmed:
        raise PixivError('temp_identity_unconfirmed')
    result['page'] = parsed[1]
    return result


def attach(db, image, evidence):
    if evidence is None:
        return
    # User confirms per-file labels. Never add the work's other characters.
    apply_metadata(db, image, evidence['art'], evidence['page'], apply_tag_matches=False)


def shutdown():
    with LOCK:
        for run in RUNS.values():
            _close(run)
        RUNS.clear()
