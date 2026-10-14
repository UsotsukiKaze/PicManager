"""Regressions for buffered reading, queue isolation and repeated API work."""

import threading
from datetime import datetime, timedelta

import pytest

from test_pixiv_ol import environment, artwork, FakeProvider
from app import models
from app.integrations.pixiv_ol import service, jobs, provider, cart, strategies
from app.integrations.pixiv_ol.recommendations import TagIndex


def test_current_batch_is_not_evicted_by_newer_bookmark_records(environment):
    context, _, _ = environment
    with context() as db:
        account = db.get(models.PixivAccount, 1)
        source = strategies.source_key('recommended', 'personal', 1)
        account.sync_state = {source: {'batch': 'source-batch'}}
        old = datetime.utcnow() - timedelta(days=1)
        for n in range(1002):
            pid = str(10000 + n)
            db.add(models.PixivArtwork(account_revision='rev', pid=pid, author_id='9', title='test',
                published_at=old,
                fetched_at=old if n == 0 else datetime.utcnow(),
                metadata_json=service.normalize_artwork(artwork(pid)),
                origins=[{'source':source, 'batch':'source-batch', 'rank':1}] if n == 0 else [{'source':'bookmarks'}]))
    with context() as db:
        candidates = strategies._candidates(db, TagIndex(db), db.get(models.PixivAccount, 1), 'personal', 1, ())
        assert [item['pid'] for item, _ in candidates] == ['10000']


def test_prefetch_reserves_unread_cards_and_status_is_actor_scoped(environment):
    context, client, _ = environment
    batch_id = 'a' * 32
    with context() as db:
        db.add(models.PixivRecommendationBatch(id=batch_id, account_revision='rev', mode='personal',
            items=[{'pid':'101'}, {'pid':'102'}], profile={'actor_id':1}))
    response = client.post('/api/pixiv-ol/browse', json={
        'view':'recommendations', 'mode':'personal', 'batch_id':batch_id, 'seen_pids':['101']})
    assert response.status_code == 202
    job_id = response.json()['id']
    with context() as db:
        assert db.get(models.PixivJob, job_id).payload['seen_pids'] == ['101', '102']
    assert client.get(f'/api/pixiv-ol/jobs/{job_id}').status_code == 200
    client.cookies.set('session_id', 'session-2')
    assert client.get(f'/api/pixiv-ol/jobs/{job_id}').status_code == 404
    assert client.post('/api/pixiv-ol/browse', json={
        'view':'recommendations', 'mode':'personal', 'batch_id':batch_id}).status_code == 409


def test_original_cache_does_not_block_recommendation_worker(environment, monkeypatch):
    context, _, _ = environment
    started, release, finished = threading.Event(), threading.Event(), threading.Event()
    monkeypatch.setattr(service, 'client_for_job', lambda *_: FakeProvider('fake'))

    def slow_cache(*_):
        started.set()
        assert release.wait(10)
        return {'count':1}

    monkeypatch.setattr(cart, 'cache_pages', slow_cache)
    monkeypatch.setattr(service, 'refresh_candidates', lambda *args, **kwargs: {'count':20})
    with context() as db:
        jobs.enqueue(db, 1, 'cache')
        recommendation = jobs.enqueue(db, 1, 'recommendations', {'mode':'personal', 'first_page':True}).id
    worker = jobs.Worker()
    thread = threading.Thread(target=lambda:(worker.run_once('background'), finished.set()))
    thread.start()
    try:
        assert started.wait(5)
        assert worker.run_once('recommendations')
        assert not finished.is_set()
        with context() as db:
            assert db.get(models.PixivJob, recommendation).status == 'completed'
    finally:
        release.set()
        thread.join(10)


def test_one_refresh_builds_interest_profile_once(environment, monkeypatch):
    calls = []
    original = strategies.build_profile
    def counted(*args):
        calls.append(1)
        return original(*args)
    monkeypatch.setattr(strategies, 'build_profile', counted)
    service.refresh_candidates(FakeProvider('fake'), 'rev', 1, 'personal', progressive=True)
    assert len(calls) == 1


def test_match_cache_is_versioned_and_returns_independent_results(environment):
    context, _, _ = environment
    tags = [{'name':'custom'}]
    with context() as db:
        index = TagIndex(db)
        assert index.match(tags)['feature_tag_ids'] == []
        db.add(models.PixivTagMapping(normalized_tag='custom', original_tag='custom',
            group_context=0, target_type='feature', target_id=1))
    with context() as db:
        index = TagIndex(db)
        match = index.match(tags)
        assert match['feature_tag_ids'] == [1]
        match['feature_tag_ids'].clear()
        assert index.match(tags)['feature_tag_ids'] == [1]


def test_access_token_reused_until_expiry_and_rejection_invalidates(monkeypatch):
    calls = []
    class API:
        def __init__(self, **kwargs): self.requests = self
        def close(self): pass
        def auth(self, refresh_token):
            calls.append('auth')
            self.access_token, self.refresh_token, self.user_id = 'access', 'rotated', 7
            return {'response':{'user':{'id':7}, 'expires_in':3600}}
        def set_auth(self, access, refresh): self.access_token, self.refresh_token = access, refresh
        def illust_detail(self, **kwargs): raise provider.PixivError('reauth_required')
    monkeypatch.setattr(provider, 'BoundedAPI', API)
    monkeypatch.setattr(provider, 'proxy_url', lambda: None)
    monkeypatch.setattr(provider, 'throttle', lambda: None)
    monkeypatch.setattr(provider.Provider, '_auth_cache', provider.OrderedDict())
    first = provider.Provider('initial')
    first.close()
    second = provider.Provider('rotated')
    assert calls == ['auth']
    with pytest.raises(provider.PixivError): second.call('illust_detail', illust_id='1')
    provider.Provider('rotated').close()
    assert calls == ['auth', 'auth']
    for entry in provider.Provider._auth_cache.values(): entry['expires'] = 0
    provider.Provider('rotated').close()
    assert calls == ['auth', 'auth', 'auth']
    second.close()


def test_parallel_workers_accept_the_same_rotated_credential(environment, monkeypatch):
    from concurrent.futures import ThreadPoolExecutor
    context, _, _ = environment
    entered, release = threading.Event(), threading.Event()
    class Remote(FakeProvider):
        def __init__(self, token):
            if not entered.is_set():
                entered.set()
                assert release.wait(5)
    monkeypatch.setattr(service, 'Provider', Remote)
    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(service.client_for_job, 1, 'rev')
        assert entered.wait(5)
        second = pool.submit(service.client_for_job, 1, 'rev')
        release.set()
        first.result(5).close()
        second.result(5).close()
    with context() as db:
        assert provider.decrypt(db.get(models.PixivAccount, 1).credential) == FakeProvider.token
