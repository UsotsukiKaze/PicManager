import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta

import pytest
from PIL import Image

from test_pixiv_ol import environment, artwork
from app import models, pixiv_check, pixiv_check_queue as queue
from app.config import settings
from app.integrations.pixiv_ol import service, provider
from app.routers import system


@pytest.fixture
def queued(environment, monkeypatch):
    context, client, root = environment
    for module in (queue, pixiv_check, system):
        monkeypatch.setattr(module, "get_db_context", context)
    monkeypatch.setattr(settings, "PIXIV_SCAN_INTERVAL_SECONDS", 0)
    monkeypatch.setattr(settings, "PIXIV_CHECK_WORKERS", 3)
    monkeypatch.setattr(pixiv_check, "download", lambda url, path, **kwargs: Image.new('RGB', (32, 20), 'blue').save(path, format='PNG'))

    def add(count):
        with context() as db:
            for index in range(1, count + 1):
                path = root / f"source-{index}.png"
                Image.new('RGB', (32, 20), 'red').save(path)
                db.add(models.Image(image_id=f"{index:010d}", pid=f"{100+index}_p0", file_path=str(path), file_extension="png",
                                    groups=[db.get(models.Group, 1)]))

    return context, client, add


def client_factory(monkeypatch, *, first_review=False, barrier=None, calls=None):
    class Client:
        def call(self, method, **kwargs):
            pid = str(kwargs['illust_id'])
            if calls is not None:
                calls.append(pid)
            if barrier:
                barrier.wait(timeout=5)
            raw = artwork(pid, pages=2 if first_review and pid == '101' else 1)
            raw.update(width=32, height=20)
            return {'illust': raw}
        def close(self):
            pass
    monkeypatch.setattr(service, 'client_for_job', lambda *_: Client())


def drain(worker):
    for _ in range(30):
        if not worker.run_once():
            return
    raise AssertionError('Queue failed to finish')


def test_unresolved_review_does_not_block_later_images_and_survives_another_run(queued, monkeypatch):
    context, client, add = queued
    add(3)
    calls = []
    client_factory(monkeypatch, first_review=True, calls=calls)
    result = client.post('/api/system/pixiv-check/queue')
    assert result.status_code == 200
    run_id = result.json()['id']
    assert client.post('/api/system/pixiv-check/queue').json()['id'] == run_id
    drain(queue.PixivCheckWorker())
    status = client.get('/api/system/pixiv-check/queue').json()
    assert status['run']['status'] == 'completed' and status['review_count'] == 1
    assert calls == ['101', '102', '103']
    review_id = status['reviews'][0]['id']
    with context() as db:
        assert db.get(models.Image, '0000000001').pixiv_checked_at is None
        assert db.get(models.Image, '0000000002').pixiv_checked_at is not None
        assert db.get(models.Image, '0000000003').pixiv_checked_at is not None
    client.post('/api/system/pixiv-check/queue')
    drain(queue.PixivCheckWorker())
    assert calls == ['101', '102', '103']
    assert client.get('/api/system/pixiv-check/queue').json()['reviews'][0]['id'] == review_id
    detail = client.get(f'/api/system/pixiv-check/reviews/{review_id}').json()
    assert detail['suggested_page'] == 0
    saved = client.post('/api/system/pixiv-check/resolve', json={
        'review_id': review_id, 'current_page': 0, 'pages': [], 'upgrade': False,
    })
    assert saved.status_code == 200
    assert client.get('/api/system/pixiv-check/queue').json()['review_count'] == 0
    with context() as db:
        assert db.get(models.Image, '0000000001').pixiv_checked_at is not None
        assert db.query(models.PixivCheckItem).filter_by(review_id=review_id).one().status == 'completed'


def test_workers_do_real_parallel_io_with_separate_clients_and_exactly_once_claims(queued, monkeypatch):
    context, _, add = queued
    add(6)
    calls, created = [], []
    barrier = threading.Barrier(3)
    client_factory(monkeypatch, barrier=barrier, calls=calls)
    factory = service.client_for_job
    def create(*args):
        client = factory(*args)
        created.append(client)
        return client
    monkeypatch.setattr(service, 'client_for_job', create)
    queue.start(1)
    prep = queue.PixivCheckWorker()
    assert prep.run_once()  # Fingerprint preparation does not require a network client.
    workers = [queue.PixivCheckWorker() for _ in range(3)]
    def run(worker):
        try:
            for _ in range(2):
                assert worker.run_once()
        finally:
            worker.close_client()
    with ThreadPoolExecutor(max_workers=3) as pool:
        list(pool.map(run, workers))
    assert len(created) == 3 and len({id(client) for client in created}) == 3
    assert len(calls) == 6 and len(set(calls)) == 6
    assert queue.status(1)['run']['status'] == 'completed'
    with context() as db:
        assert all(image.pixiv_checked_at for image in db.query(models.Image).all())
        assert all(item.attempts == 1 for item in db.query(models.PixivCheckItem).all())


def test_database_claim_limits_concurrency_and_recovers_expired_lease(queued):
    context, _, add = queued
    add(4)
    queue.start(1)
    tasks = [queue.claim() for _ in range(3)]
    assert all(tasks) and queue.claim() is None
    with context() as db:
        db.get(models.PixivCheckItem, tasks[0]['id']).locked_at = datetime.utcnow() - timedelta(seconds=301)
    recovered = queue.claim()
    assert recovered['id'] == tasks[0]['id'] and recovered['lease'] != tasks[0]['lease']
    with context() as db:
        with pytest.raises(provider.PixivError, match='check_cancelled'):
            queue.guard(db, tasks[0]['id'], tasks[0]['lease'])


def test_stop_during_fetch_prevents_late_image_mutation_and_preserves_pending_reviews(queued, monkeypatch):
    context, _, add = queued
    add(2)
    client_factory(monkeypatch, first_review=True)
    run_id = queue.start(1)['id']
    worker = queue.PixivCheckWorker()
    assert worker.run_once() and worker.run_once()  # preparation + first review
    class Client:
        def call(self, *_args, **kwargs):
            queue.stop(1, run_id)
            raw = artwork('102');raw.update(width=32, height=20)
            return {'illust': raw}
        def close(self): pass
    worker.close_client()
    monkeypatch.setattr(service, 'client_for_job', lambda *_: Client())
    assert worker.run_once()
    status = queue.status(1)
    assert status['run']['status'] == 'cancelled' and status['review_count'] == 1
    with context() as db:
        assert all(image.pixiv_checked_at is None for image in db.query(models.Image).all())
        assert db.get(models.Image, '0000000002').pixiv_metadata is None


def test_failed_image_can_retry_without_blocking_other_items_or_marking_checked(queued, monkeypatch):
    context, _, add = queued
    add(2)
    calls = []
    class Client:
        def call(self, *_args, **kwargs):
            pid = str(kwargs['illust_id']);calls.append(pid)
            if pid == '101': raise provider.PixivError('external_error')
            raw = artwork(pid);raw.update(width=32, height=20)
            return {'illust': raw}
        def close(self): pass
    monkeypatch.setattr(service, 'client_for_job', lambda *_: Client())
    queue.start(1)
    worker = queue.PixivCheckWorker()
    assert worker.run_once() and worker.run_once() and worker.run_once()
    with context() as db:
        assert db.get(models.Image, '0000000001').pixiv_checked_at is None
        assert db.get(models.Image, '0000000002').pixiv_checked_at is not None
        item = db.query(models.PixivCheckItem).filter_by(image_id='0000000001').one()
        assert item.status == 'queued' and item.error == 'external_error'
        item.available_at = datetime.utcnow() - timedelta(seconds=1)
    client_factory(monkeypatch)
    worker.close_client()
    assert worker.run_once()
    assert queue.status(1)['run']['status'] == 'completed'


def test_queue_endpoints_keep_admin_actor_and_origin_boundaries(queued):
    _, client, add = queued
    add(1)
    run_id = client.post('/api/system/pixiv-check/queue').json()['id']
    client.cookies.set('session_id', 'session-2')
    assert client.post('/api/system/pixiv-check/queue').status_code == 409
    assert client.post(f'/api/system/pixiv-check/queue/{run_id}/stop').status_code == 404
    client.cookies.set('session_id', 'session-3')
    assert client.get('/api/system/pixiv-check/queue').status_code == 403
    client.cookies.set('session_id', 'session-1')
    assert client.post('/api/system/pixiv-check/queue', headers={'Origin':'https://evil.test'}).status_code == 403


def test_account_change_during_fetch_stops_run_without_marking_or_tagging_image(queued, monkeypatch):
    context, _, add = queued
    add(2)
    class Client:
        def call(self, *_args, **kwargs):
            with context() as db:
                db.get(models.PixivAccount, 1).revision = 'changed'
            raw = artwork('101');raw.update(width=32, height=20)
            return {'illust': raw}
        def close(self): pass
    monkeypatch.setattr(service, 'client_for_job', lambda *_: Client())
    queue.start(1)
    worker = queue.PixivCheckWorker()
    assert worker.run_once() and worker.run_once()
    assert queue.status(1)['run']['status'] == 'failed'
    with context() as db:
        assert all(image.pixiv_checked_at is None and not image.feature_tags for image in db.query(models.Image).all())
        assert db.query(models.PixivCheckReview).count() == 0


def test_graceful_worker_shutdown_requeues_inflight_image_for_new_worker(queued, monkeypatch):
    context, _, add = queued
    add(1)
    worker = queue.PixivCheckWorker()
    class Client:
        def call(self, *_args, **kwargs):
            worker.stop_event.set()
            raw = artwork('101');raw.update(width=32, height=20)
            return {'illust': raw}
        def close(self): pass
    monkeypatch.setattr(service, 'client_for_job', lambda *_: Client())
    queue.start(1)
    assert worker.run_once() and worker.run_once()
    with context() as db:
        item = db.query(models.PixivCheckItem).filter_by(image_id='0000000001').one()
        assert item.status == 'queued' and not item.lease
        assert db.get(models.Image, item.image_id).pixiv_checked_at is None
    client_factory(monkeypatch)
    drain(queue.PixivCheckWorker())
    assert queue.status(1)['run']['status'] == 'completed'


def test_resume_reuses_committed_review_after_worker_crash(queued, monkeypatch):
    context, _, add = queued
    add(1)
    calls = []
    client_factory(monkeypatch, first_review=True, calls=calls)
    queue.start(1)
    worker = queue.PixivCheckWorker()
    assert worker.run_once() and worker.run_once()
    review_id = queue.status(1)['reviews'][0]['id']
    with context() as db:
        # Simulate the gap after committing the review but before committing queue completion.
        item = db.query(models.PixivCheckItem).filter_by(image_id='0000000001').one()
        item.status, item.review_id = 'running', None
        item.locked_at, item.lease = datetime.utcnow()-timedelta(seconds=301), 'lost-lease'
        run = db.get(models.PixivCheckRun, item.run_id)
        run.status, run.active_key, run.finished_at = 'running', 'pixiv-check', None
    assert queue.PixivCheckWorker().run_once()
    assert calls == ['101']
    assert queue.status(1)['reviews'][0]['id'] == review_id


def test_account_change_before_claim_finishes_batch_instead_of_reclaiming_forever(queued):
    context, _, add = queued
    add(1)
    queue.start(1)
    with context() as db:
        db.get(models.PixivAccount, 1).revision = 'changed'
    worker = queue.PixivCheckWorker()
    assert worker.run_once()
    assert not worker.run_once()
    result = queue.status(1)['run']
    assert result['status'] == 'failed' and result['error'] == 'account_changed'
    with context() as db:
        assert db.get(models.Image, '0000000001').pixiv_checked_at is None


def test_concurrent_clients_serialize_refresh_token_rotation(queued, monkeypatch):
    entered, release = threading.Event(), threading.Event()
    seen = []
    class Client:
        def __init__(self, token):
            seen.append(token)
            if len(seen) == 1:
                entered.set()
                assert release.wait(timeout=5)
            self.token, self.user = token + 'x', {'id': '7'}
        def close(self): pass
    monkeypatch.setattr(service, 'Provider', Client)
    with ThreadPoolExecutor(max_workers=3) as pool:
        futures = [pool.submit(service.client_for_job, 1, 'rev') for _ in range(3)]
        assert entered.wait(timeout=5)
        release.set()
        clients = [future.result(timeout=5) for future in futures]
    assert seen == ['test-token', 'test-tokenx', 'test-tokenxx']
    assert len({id(client) for client in clients}) == 3


def test_same_artwork_concurrent_checks_recover_cache_insert_conflicts(queued, monkeypatch):
    context, _, add = queued
    add(3)
    with context() as db:
        for image in db.query(models.Image).all():
            image.pid = '101_p0'
    barrier = threading.Barrier(3)
    call_lock = threading.Lock()
    calls = []
    class Client:
        def call(self, *_args, **kwargs):
            with call_lock:
                calls.append(kwargs['illust_id'])
                number = len(calls)
            if number <= 3:
                barrier.wait(timeout=5)
            raw = artwork('101');raw.update(width=32, height=20)
            return {'illust': raw}
        def close(self): pass
    monkeypatch.setattr(service, 'client_for_job', lambda *_: Client())
    queue.start(1)
    worker = queue.PixivCheckWorker()
    assert worker.run_once()  # prepare
    with ThreadPoolExecutor(max_workers=3) as pool:
        assert all(pool.map(lambda _: worker.run_once(), range(3)))
    with context() as db:
        for item in db.query(models.PixivCheckItem).filter_by(status='queued').all():
            item.available_at = datetime.utcnow() - timedelta(seconds=1)
    drain(worker)
    with context() as db:
        assert all(image.pixiv_checked_at is not None for image in db.query(models.Image).all())
        assert db.query(models.PixivArtwork).filter_by(pid='101').count() == 1
        assert not db.query(models.PixivCheckItem).filter_by(status='failed').count()


@pytest.mark.parametrize('pages', [1, 2])
def test_validation_preserves_manual_labels_across_pages_and_duplicate_pids(queued, monkeypatch, pages):
    context, _, add = queued
    add(3)
    with context() as db:
        db.add(models.Group(id=2, name='另一个分组'))
        db.add_all([models.Character(id=10, name='角色甲', group_id=1),
                    models.Character(id=11, name='角色乙', group_id=2)])
        db.flush()
        for index in range(1, 4):
            image = db.get(models.Image, f'{index:010d}')
            image.pid = f'101_p{1 if pages == 2 and index == 2 else 0}'
            image.characters = [db.get(models.Character, 11 if index == 2 else 10)] if index < 3 else []
            image.groups = [db.get(models.Group, 2 if index == 2 else 1)]
            image.feature_tags = [db.get(models.FeatureTag, 1)]
    class Client:
        def call(self, *_args, **kwargs):
            raw = artwork('101', pages=pages, tags=[{'name': '角色甲'}, {'name': '角色乙'}])
            raw.update(width=32, height=20)
            return {'illust': raw}
        def close(self): pass
    monkeypatch.setattr(service, 'client_for_job', lambda *_: Client())
    queue.start(1)
    drain(queue.PixivCheckWorker())
    details = [queue.get_review(1, review['id']) for review in queue.status(1)['reviews']]
    for detail in sorted(details, key=lambda item: item['current']['image_id']):
        pixiv_check.resolve(detail['review_id'], 1, detail['suggested_page'], [], False)
    with context() as db:
        for index, expected in enumerate(([10], [11], []), 1):
            image = db.get(models.Image, f'{index:010d}')
            assert [character.id for character in image.characters] == expected
            assert [group.id for group in image.groups] == [2 if index == 2 else 1]
            assert {tag.name for tag in image.feature_tags} == {'白发', 'Pixiv'}
            assert image.pixiv_checked_at and [tag['name'] for tag in image.pixiv_metadata.tags] == ['角色甲', '角色乙']
            assert image.pixiv_metadata.page_index == (1 if pages == 2 and index == 2 else 0)
        assert db.query(models.PixivTagMapping).filter_by(target_type='character').count() == 2
        assert db.query(models.PixivImageSource).filter_by(work_id='101', page_index=0).one().image_id == '0000000001'


def test_non_cart_import_metadata_keeps_each_pages_confirmed_character(queued):
    from app.integrations.pixiv_ol.jobs import add_source
    context, _, add = queued
    add(2)
    with context() as db:
        db.add_all([models.Character(id=10, name='角色甲', group_id=1),
                    models.Character(id=11, name='角色乙', group_id=1)])
        db.flush()
        art = service.normalize_artwork(artwork('101', pages=2, tags=[{'name': '角色甲'}, {'name': '角色乙'}]))
        for index, character in enumerate((10, 11), 1):
            image = db.get(models.Image, f'{index:010d}')
            image.characters = [db.get(models.Character, character)]
            add_source(db, image.image_id, '101', index - 1, 'digest', art)
    with context() as db:
        assert [c.id for c in db.get(models.Image, '0000000001').characters] == [10]
        assert [c.id for c in db.get(models.Image, '0000000002').characters] == [11]
