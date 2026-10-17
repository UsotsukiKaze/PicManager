"""Bounded, detached recommendation profiles with transaction-aware invalidation."""
from collections import OrderedDict
from copy import deepcopy
import json
import threading
import time
from weakref import WeakKeyDictionary

LOCK = threading.RLock()
STORES = WeakKeyDictionary()
TTL = 60


def store_for(bind):
    with LOCK:
        return STORES.setdefault(bind, {'revision': 0, 'entries': OrderedDict(), 'building': {}})


def invalidate(bind):
    with LOCK:
        store = store_for(bind)
        store['revision'] += 1
        for key in list(store['entries']):
            if key[0] is not None:
                store['entries'].pop(key, None)


def cached_profile(db, index, account, mode, build, *, training_sensitive=True):
    # A caller inspecting a not-yet-committed edit must see its own changes.
    from sqlalchemy import inspect
    pending = any(inspect(obj).mapper.local_table.name not in (
        'pixiv_accounts', 'pixiv_jobs', 'pixiv_recommendation_batches', 'pixiv_recommendation_exposures')
        for obj in db.dirty)
    if db.new or pending or db.deleted or db.info.get('pol_profile_changed'):
        return build()
    store = store_for(db.get_bind())
    while True:
        with LOCK:
            revision = store['revision'] if training_sensitive else None
            key = (revision, index.signature, account.revision, mode,
                   getattr(account, 'owner_id', None), json.dumps(account.preferences, sort_keys=True, ensure_ascii=True))
            hit = store['entries'].get(key)
            if hit and time.monotonic() < hit[0]:
                store['entries'].move_to_end(key)
                return deepcopy(hit[1])
            pending = store['building'].get(key)
            if pending is None:
                pending = store['building'][key] = threading.Event()
                break
        pending.wait()
    try:
        result = build()
        with LOCK:
            if not training_sensitive or store['revision'] == revision:
                store['entries'][key] = (time.monotonic() + TTL, deepcopy(result))
                while len(store['entries']) > 8:
                    store['entries'].popitem(last=False)
        return result
    finally:
        with LOCK:
            store['building'].pop(key, None)
            pending.set()
