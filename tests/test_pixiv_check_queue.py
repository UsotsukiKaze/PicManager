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


@pytest.mark.parametrize('existing_review', [False, True])
def test_legacy_hd_marker_does_not_hide_or_repeatedly_scan_multipage_review(queued, monkeypatch, existing_review):
    context, client, add = queued
    add(2)
    calls=[]
    client_factory(monkeypatch, first_review=True, calls=calls)
    with context() as db:
        image=db.get(models.Image, '0000000001')
        image.pixiv_checked_at=datetime(2026, 1, 1)
        if existing_review:
            art=service.normalize_artwork(artwork('101', pages=2))
            db.add(models.PixivCheckReview(id='a'*48, image_id=image.image_id, actor_id=1,
                account_revision='rev',snapshot=pixiv_check.snapshot(image),artwork=art,
                expires_at=datetime.utcnow()+timedelta(days=1)))
    queue.start(1);drain(queue.PixivCheckWorker())
    status=client.get('/api/system/pixiv-check/queue').json()
    assert status['review_count']==1 and status['run']['status']=='completed'
    assert calls==(['102'] if existing_review else ['101','102'])
    review=status['reviews'][0]['id']
    assert client.get(f'/api/system/pixiv-check/reviews/{review}').status_code==200
    queue.start(1);drain(queue.PixivCheckWorker())
    assert client.get('/api/system/pixiv-check/queue').json()['review_count']==1
    assert client.post('/api/system/pixiv-check/resolve',json={'review_id':review,'current_page':1,'pages':[],'upgrade':False}).status_code==200
    with context() as db:
        assert db.get(models.Image,'0000000001').pid=='101_p1'


@pytest.mark.parametrize('failed_samples', [True, False])
def test_bare_pid_sample_failure_or_ambiguous_pages_stays_reviewable_and_does_not_block(queued, monkeypatch, failed_samples):
    context, _, add=queued
    add(2)
    with context() as db:db.get(models.Image,'0000000001').pid='101'
    client_factory(monkeypatch,first_review=True)
    if failed_samples:
        def unavailable(*_args,**_kwargs):raise provider.PixivError('download_failed')
        monkeypatch.setattr(pixiv_check,'download',unavailable)
    queue.start(1);drain(queue.PixivCheckWorker())
    status=queue.status(1)
    assert status['run']['status']=='completed' and status['review_count']==1
    assert not status['run']['counts'].get('failed')
    detail=queue.get_review(1,status['reviews'][0]['id'])
    assert detail['suggested_page'] is None
    assert detail['page_matching']['status']==('preview_failed' if failed_samples else 'ambiguous')
    with context() as db:
        assert db.get(models.Image,'0000000001').pixiv_checked_at is None
        assert db.get(models.Image,'0000000002').pixiv_checked_at is not None
    pixiv_check.resolve(detail['review_id'],1,1,[],False)
    assert queue.status(1)['review_count']==0


def test_explicit_deleted_work_clears_pid_and_stale_sources_but_keeps_file_and_labels(queued, monkeypatch):
    from app.services import ImageService
    context, _, add=queued
    add(1)
    with context() as db:
        image=db.get(models.Image,'0000000001');image.feature_tags=[db.get(models.FeatureTag,1)]
        db.add(models.Character(id=10,name='角色甲',group_id=1));db.flush()
        image.characters=[db.get(models.Character,10)]
        db.add(models.PixivArtist(id='9',name='旧画师'));db.flush()
        image.pixiv_metadata=models.PixivImageMetadata(work_id='101',page_index=0,page_count=0,status='unavailable',artist_id='9')
        image.pixiv_checked_at=datetime(2026,1,1)
        db.add(models.PixivImageSource(image_id=image.image_id,work_id='101',page_index=0,sha256='old',metadata_json={}))
        before=ImageService.image_full_path(image)
    class Client:
        def call(self,*_args,**_kwargs):raise provider.PixivError('artwork_unavailable')
        def close(self):pass
    monkeypatch.setattr(service,'client_for_job',lambda *_:Client())
    queue.start(1);drain(queue.PixivCheckWorker())
    assert queue.status(1)['run']['invalid_pids']==1
    with context() as db:
        image=db.get(models.Image,'0000000001')
        assert image.pid is None and image.pixiv_metadata is None and image.pixiv_checked_at is None
        assert image.file_path==before and ImageService.image_file_exists(image)
        assert [c.id for c in image.characters]==[10] and [g.id for g in image.groups]==[1]
        assert [t.id for t in image.feature_tags]==[1]
        assert not image.pixiv_sources and not db.query(models.PixivArtist).count()
        assert image.visual_fingerprint is not None


@pytest.mark.parametrize('error',['external_error','access_denied','rate_limited','unsupported'])
def test_network_permission_or_unsupported_work_never_clears_pid(queued,monkeypatch,error):
    context, _, add=queued
    add(1)
    class Client:
        def call(self,*_args,**_kwargs):
            if error!='unsupported':raise provider.PixivError(error)
            raw=artwork('101');raw['type']='ugoira';return {'illust':raw}
        def close(self):pass
    monkeypatch.setattr(service,'client_for_job',lambda *_:Client())
    queue.start(1);worker=queue.PixivCheckWorker()
    assert worker.run_once() and worker.run_once()
    with context() as db:
        image=db.get(models.Image,'0000000001')
        assert image.pid=='101_p0' and image.pixiv_checked_at is None
        assert image.pixiv_metadata is None


def make_check_retry_due(context):
    with context() as db:
        db.query(models.PixivCheckItem).filter_by(status='queued').update(
            {'available_at': datetime.utcnow() - timedelta(seconds=1)}, synchronize_session=False)


@pytest.mark.parametrize('code', ['access_deny', 'access_denied', 'invisible'])
def test_three_consecutive_detail_denials_clear_pid_without_a_failed_item(queued, monkeypatch, code):
    from app.services import ImageService
    context, _, add = queued
    add(2)
    with context() as db:
        image = db.get(models.Image, '0000000001')
        image.feature_tags = [db.get(models.FeatureTag, 1)]
        path = ImageService.image_full_path(image)
    calls = []
    class Client:
        def call(self, *_args, **kwargs):
            pid = str(kwargs['illust_id']);calls.append(pid)
            if pid == '101':
                if code == 'invisible':
                    raw = artwork(pid);raw['visible'] = False;return {'illust': raw}
                raise provider.PixivError(code)
            raw = artwork(pid);raw.update(width=32, height=20);return {'illust': raw}
        def close(self): pass
    monkeypatch.setattr(service, 'client_for_job', lambda *_: Client())
    queue.start(1);worker = queue.PixivCheckWorker()
    assert worker.run_once() and worker.run_once() and worker.run_once()
    for count in (1, 2):
        with context() as db:
            image = db.get(models.Image, '0000000001')
            task = db.query(models.PixivCheckItem).filter_by(image_id=image.image_id).one()
            assert image.pid == '101_p0' and task.status == 'queued'
            assert task.result['count'] == count
            assert db.get(models.Image, '0000000002').pixiv_checked_at is not None
        assert not queue.status(1)['run']['errors']
        make_check_retry_due(context)
        assert worker.run_once()
    drain(worker)
    state = queue.status(1)
    assert state['run']['invalid_pids'] == 1 and not state['run']['errors']
    with context() as db:
        image = db.get(models.Image, '0000000001')
        task = db.query(models.PixivCheckItem).filter_by(image_id=image.image_id).one()
        assert image.pid is None and image.pixiv_checked_at is None and image.pixiv_metadata is None
        assert task.status == 'completed' and task.error is None
        assert task.result['reason'] == 'access_deny'
        assert ImageService.image_file_exists(image) and ImageService.image_full_path(image) == path
        assert [tag.id for tag in image.feature_tags] == [1] and [group.id for group in image.groups] == [1]
        assert image.visual_fingerprint is not None
    assert calls.count('101') == 3


def test_other_error_breaks_denial_streak_and_success_preserves_pid(queued, monkeypatch):
    context, _, add = queued
    add(1)
    errors = iter(['access_deny', 'external_error', 'access_denied', 'access_deny', None])
    class Client:
        def call(self, *_args, **kwargs):
            code = next(errors)
            if code:raise provider.PixivError(code)
            raw = artwork('101');raw.update(width=32, height=20);return {'illust': raw}
        def close(self): pass
    monkeypatch.setattr(service, 'client_for_job', lambda *_: Client())
    queue.start(1);worker = queue.PixivCheckWorker();assert worker.run_once()
    for expected in (1, None, 1, 2):
        make_check_retry_due(context);assert worker.run_once()
        with context() as db:
            task = db.query(models.PixivCheckItem).filter_by(image_id='0000000001').one()
            assert (task.result or {}).get('count') == expected
            assert task.status == 'queued'
            assert db.get(models.Image, '0000000001').pid == '101_p0'
    make_check_retry_due(context);drain(worker)
    with context() as db:
        image = db.get(models.Image, '0000000001')
        assert image.pid == '101_p0' and image.pixiv_checked_at is not None
    assert queue.status(1)['run']['invalid_pids'] == 0


def test_pid_change_resets_denials_and_stop_prevents_third_denial_mutation(queued, monkeypatch):
    context, _, add = queued
    add(1)
    run_id = queue.start(1)['id'];calls = []
    class Client:
        def call(self, *_args, **kwargs):
            calls.append(kwargs['illust_id'])
            if len(calls) == 4:queue.stop(1, run_id)
            raise provider.PixivError('access_deny')
        def close(self): pass
    monkeypatch.setattr(service, 'client_for_job', lambda *_: Client())
    worker = queue.PixivCheckWorker();assert worker.run_once() and worker.run_once()
    with context() as db:db.get(models.Image, '0000000001').pid = '102_p0'
    for expected in (1, 2):
        make_check_retry_due(context);assert worker.run_once()
        with context() as db:
            task = db.query(models.PixivCheckItem).filter_by(image_id='0000000001').one()
            assert task.result['count'] == expected
            assert db.get(models.Image, '0000000001').pid == '102_p0'
    make_check_retry_due(context);assert worker.run_once()
    with context() as db:assert db.get(models.Image, '0000000001').pid == '102_p0'
    assert queue.status(1)['run']['status'] == 'cancelled'


def test_account_authorization_denial_never_counts_as_deleted_artwork(queued, monkeypatch):
    context, _, add = queued
    add(1)
    def no_account_client(*_args):raise provider.PixivError('access_denied')
    monkeypatch.setattr(service, 'client_for_job', no_account_client)
    queue.start(1);worker = queue.PixivCheckWorker();assert worker.run_once()
    for _ in range(3):
        make_check_retry_due(context);assert worker.run_once()
    with context() as db:
        assert db.get(models.Image, '0000000001').pid == '101_p0'
        task = db.query(models.PixivCheckItem).filter_by(image_id='0000000001').one()
        assert task.status == 'failed' and task.result is None


def test_extra_page_duplicate_is_visible_in_maintenance_and_can_resume_import(queued,monkeypatch):
    from app.services import ImageService
    from app.integrations.pixiv_ol import jobs
    context, client, add=queued
    add(1)
    with context() as db:
        image=db.get(models.Image,'0000000001')
        image.perceptual_hash=ImageService.compute_dhash(image.file_path)
    client_factory(monkeypatch,first_review=True)
    monkeypatch.setattr(jobs,'download',lambda url,path,**kwargs:Image.new('RGB',(32,20),'blue').save(path,format='PNG'))
    queue.start(1);drain(queue.PixivCheckWorker())
    review=queue.status(1)['reviews'][0]['id']
    saved=pixiv_check.resolve(review,1,0,[1],False)
    assert jobs.Worker().run_once()
    data=client.get('/api/system/pixiv-check/queue').json()
    assert data['review_count']==0 and data['import_count']==1
    supplement=data['imports'][0]
    assert supplement['status']=='awaiting_duplicate' and supplement['page']==1
    assert supplement['duplicates'][0]['image_id']=='0000000001'
    assert client.post(f"/api/pixiv-ol/imports/{saved['import_job_id']}/resolve",json={'action':'different'}).status_code==202
    assert jobs.Worker().run_once()
    assert queue.status(1)['imports']==[]
    with context() as db:assert db.query(models.Image).filter_by(pid='101_p1').count()==1


def test_uppercase_local_cursor_is_valid_and_incremental_route_is_used(queued,monkeypatch):
    from app import local_check
    _,client,_=queued
    seen=[]
    monkeypatch.setattr(local_check,'run_batch',lambda db,after_id,limit,**kw:seen.append((after_id,kw)) or {'processed':0})
    assert client.post('/api/system/local-check?after_id=1C2476F04F').status_code==200
    assert seen==[('1C2476F04F',{'incremental':True})]
    assert client.post('/api/system/local-check?after_id=bad-cursor').status_code==422


def test_incremental_local_validation_releases_writer_between_image_decodes(queued,monkeypatch):
    from app import local_check
    from app.services import ImageService
    context,_,add=queued;add(2)
    monkeypatch.setattr(ImageService,'cleanup_orphaned_records',lambda *a,**kw:0)
    monkeypatch.setattr(ImageService,'move_orphaned_files_to_temp',lambda *a,**kw:0)
    calls=[]
    def thumbnail(image):
        calls.append(image.image_id)
        if len(calls)==2:
            with context() as concurrent:
                concurrent.get(models.Group,1).name='并发写入成功'
        image.thumb_status='ready';return True
    monkeypatch.setattr(ImageService,'ensure_thumbnail',thumbnail)
    with context() as db:assert local_check.run_batch(db,incremental=True)['ready']==2
    with context() as db:assert db.get(models.Group,1).name=='并发写入成功'


def test_derivative_worker_survives_database_lock_and_continues(queued,monkeypatch):
    import sqlite3
    from sqlalchemy.exc import OperationalError
    from app.jobs import ImageJobWorker
    worker=ImageJobWorker(poll_seconds=.1);calls=[]
    def run_once():
        calls.append(1)
        if len(calls)==1:raise OperationalError('',{},sqlite3.OperationalError('database is locked'))
        worker.stop_event.set();return False
    monkeypatch.setattr(worker,'run_once',run_once)
    worker._run()
    assert len(calls)==2


def test_idle_queue_claims_do_not_issue_update_statements(queued):
    from sqlalchemy import event
    from app.jobs import ImageJobQueue
    context,_,_=queued
    with context() as db:engine=db.get_bind()
    statements=[]
    def before(_conn,_cursor,statement,_params,_context,_many):statements.append(statement)
    event.listen(engine,'before_cursor_execute',before)
    try:
        assert queue.claim() is None
        with context() as db:assert ImageJobQueue.claim(db) is None
        assert not any(sql.lstrip().upper().startswith('UPDATE') for sql in statements)
    finally:event.remove(engine,'before_cursor_execute',before)
