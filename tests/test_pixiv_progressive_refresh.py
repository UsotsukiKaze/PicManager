import pytest
from test_pixiv_ol import environment, artwork, FakeProvider
from app import models
from app.integrations.pixiv_ol import service, jobs
from app.integrations.pixiv_ol.provider import PixivError


class Pages(FakeProvider):
    def __init__(self, token, exhausted=False):
        self.calls = []
        self.exhausted = exhausted

    def call(self, method, **kwargs):
        offset = int(kwargs.get('offset', 0))
        self.calls.append((method, offset))
        base = 1000 + offset if method in ('illust_recommended', 'illust_follow') else 9000
        return {'illusts': [artwork(str(base + i)) for i in range(30)],
                'next_url': None if self.exhausted else
                    f'https://app-api.pixiv.net/v1/illust/recommended?offset={offset + 30}'}


def test_progressive_refresh_publishes_first_twenty_without_search_or_extra_pages(environment):
    context, client, _ = environment
    remote = Pages('test')
    result = service.refresh_candidates(remote, 'rev', 1, progressive=True)
    assert remote.calls == [('illust_recommended', 0)]
    first = client.get('/api/pixiv-ol/recommendations', params={'batch_id':result['batch_id'], 'limit':20}).json()
    assert len(first['items']) == 20 and first['total'] == 30
    with context() as db:
        state = db.get(models.PixivAccount, 1).sync_state['recommendation_stream_combined']
        assert state['cursor'] == {'offset':'30'} and len(state['deferred_queries']) == 1
    following = service.refresh_candidates(remote, 'rev', 1, continuation=True, progressive=True)
    assert remote.calls[1:] == [('illust_recommended', 30), ('search_illust', 0)]
    assert following['more']
    assert client.get('/api/pixiv-ol/recommendations', params={'batch_id':result['batch_id'], 'limit':20}).json() == first


def test_deferred_search_survives_native_stream_exhaustion(environment):
    context, _, _ = environment
    remote = Pages('test', exhausted=True)
    first = service.refresh_candidates(remote, 'rev', 1, progressive=True)
    assert first['more']
    second = service.refresh_candidates(remote, 'rev', 1, continuation=True, progressive=True)
    assert remote.calls == [('illust_recommended', 0), ('search_illust', 0)]
    assert not second['more'] and second['count'] > 0
    assert service.refresh_candidates(remote, 'rev', 1, continuation=True, progressive=True) == {'count':0, 'more':False}
    with context() as db:
        assert db.get(models.PixivAccount, 1).sync_state['recommendation_stream_combined']['deferred_queries'] == []


def test_progressive_native_refresh_has_one_page_and_no_local_search(environment):
    _, _, _ = environment
    remote = Pages('test')
    service.refresh_candidates(remote, 'rev', 1, 'native', progressive=True)
    service.refresh_candidates(remote, 'rev', 1, 'native', continuation=True, progressive=True)
    assert remote.calls == [('illust_recommended', 0), ('illust_recommended', 30)]


def test_progressive_following_sync_completes_first_page_and_resumes_history(environment):
    context, client, _ = environment
    remote = Pages('test')
    first = service.sync_feed(remote, 'rev', 1, first_page=True)
    assert first == {'count':30, 'partial':False, 'more':True}
    assert len(client.get('/api/pixiv-ol/feed', params={'limit':20}).json()['items']) == 20
    assert service.continue_feed(remote, 'rev', 1, progressive=True)['more']
    assert remote.calls == [('illust_follow', 0), ('illust_follow', 30)]
    with context() as db:
        assert db.get(models.PixivAccount, 1).sync_state['feed_public']['history_cursor'] == {'offset':'60'}


def test_manual_refresh_worker_uses_progressive_request(environment, monkeypatch):
    context, client, _ = environment
    remote = Pages('test')
    monkeypatch.setattr(service, 'client_for_job', lambda *_:remote)
    response = client.post('/api/pixiv-ol/sync', json={'kind':'recommendations', 'first_page':True})
    assert response.status_code == 202
    assert jobs.Worker().run_once()
    assert remote.calls == [('illust_recommended', 0)]
    with context() as db:
        assert db.get(models.PixivJob, response.json()['id']).status == 'completed'


def test_deferred_search_failure_preserves_plan_for_retry(environment, monkeypatch):
    context, _, _ = environment
    remote = Pages('test', exhausted=True)
    service.refresh_candidates(remote, 'rev', 1, progressive=True)
    original = remote.call
    def offline(method, **kwargs):
        if method == 'search_illust':
            raise PixivError('external_error')
        return original(method, **kwargs)
    monkeypatch.setattr(remote, 'call', offline)
    with pytest.raises(PixivError):
        service.refresh_candidates(remote, 'rev', 1, continuation=True, progressive=True)
    with context() as db:
        state = db.get(models.PixivAccount, 1).sync_state['recommendation_stream_combined']
        assert len(state['deferred_queries']) == 1 and state['exhausted']
    monkeypatch.setattr(remote, 'call', original)
    assert service.refresh_candidates(remote, 'rev', 1, continuation=True, progressive=True)['count'] > 0
