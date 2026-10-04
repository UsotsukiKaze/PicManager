import hashlib
from pathlib import Path

import pytest
from PIL import Image, ImageDraw

from test_pixiv_ol import environment, install_fake, artwork, FakeProvider
from test_visual_similarity import drawing
from app import models, visual_similarity
from app.config import settings
from app.integrations.pixiv_ol import jobs
from app.services import ImageService


@pytest.fixture
def waiting(environment, monkeypatch):
    context, client, root = environment
    install_fake(monkeypatch)
    monkeypatch.setattr(settings, 'THUMB_PATH', str(root/'thumbs'))
    monkeypatch.setattr(jobs, 'download', lambda _url, path, **_kw: drawing().save(path, format='PNG'))
    old = Path(settings.STORE_PATH)/'screenshot.png'
    old.parent.mkdir(parents=True, exist_ok=True)
    screen = Image.new('RGB', (760, 940), 'white')
    screen.paste(drawing().resize((360, 480)), (180, 250))
    ImageDraw.Draw(screen).rectangle((0, 0, 760, 80), fill='#242732')
    screen.save(old)
    with context() as db:
        db.add(models.Group(id=2, name='原分组'))
        db.add_all([models.Character(id=1, name='本页角色', group_id=1), models.Character(id=2, name='旧图角色', group_id=2)])
        db.flush()
        db.add(models.Image(image_id='AABBCCDDEE', file_path=str(old), file_extension='png',
            original_filename='screenshot.png', width=760, height=940, file_size=old.stat().st_size,
            perceptual_hash='ffffffffffffffff', groups=[db.get(models.Group, 2)], characters=[db.get(models.Character, 2)]))
        db.flush()
        visual_similarity.index_missing_batch(db)
    response = client.post('/api/pixiv-ol/imports', json={'pid':'100', 'pages':[0], 'group_ids':[1],
        'character_ids':[1], 'feature_tag_ids':[1], 'idempotency_key':'merge_review_test'})
    job_id = response.json()['id']
    worker = jobs.Worker()
    assert worker.run_once()
    with context() as db:
        result = db.get(models.PixivJob, job_id).result
        assert db.get(models.PixivJob, job_id).status == 'awaiting_duplicate'
    yield context, client, root, old, job_id, result, worker


def decide(waiting, action, **extra):
    _, client, _, _, job_id, result, _ = waiting
    return client.post(f'/api/pixiv-ol/imports/{job_id}/resolve', json={
        'action': action, 'image_id':'AABBCCDDEE', 'page':0, 'review_key':result['review_key'], **extra})


def test_screenshot_candidate_outside_selected_group_enters_merge_review(waiting):
    context, client, _, old, job_id, result, _ = waiting
    assert result['duplicates'][0]['algorithm'] == 'visual64-grid-v1'
    assert result['duplicates'][0]['score'] >= 94
    assert result['incoming']['pid'] == '100_p0'
    assert result['incoming']['original_filename'] == '100_p0.png'
    assert result['incoming']['character_names'] == ['本页角色']
    assert client.get(f'/api/pixiv-ol/imports/{job_id}/comparison').status_code == 200
    assert old.exists()
    with context() as db:
        assert db.query(models.Image).count() == 1
        assert db.get(models.Image, 'AABBCCDDEE').pid is None


def test_keep_existing_merges_chosen_fields_and_preserves_file_and_roles(waiting):
    context, _, _, old, job_id, _, worker = waiting
    digest = hashlib.sha256(old.read_bytes()).hexdigest()
    assert decide(waiting, 'merge_existing', metadata_sources={'characters':'keep','groups':'merge','feature_tags':'merge','pid':'other'}).status_code == 202
    assert worker.run_once()
    with context() as db:
        image = db.get(models.Image, 'AABBCCDDEE')
        assert db.query(models.Image).count() == 1 and image.pid == '100_p0'
        assert [x.id for x in image.characters] == [2]
        assert {x.id for x in image.groups} == {1, 2}
        assert image.pixiv_checked_at is not None
        assert db.get(models.PixivJob, job_id).status == 'completed'
    assert hashlib.sha256(old.read_bytes()).hexdigest() == digest


def test_keep_pixiv_original_merges_selected_old_roles_and_cleans_superseded_file(waiting):
    context, _, _, old, job_id, _, worker = waiting
    assert decide(waiting, 'merge_new', metadata_sources={'characters':'other','pid':'keep'}).status_code == 202
    assert worker.run_once()
    with context() as db:
        assert db.get(models.Image, 'AABBCCDDEE').file_status == 'archived'
        image = db.query(models.Image).filter_by(file_status='available').one()
        assert image.pid == '100_p0' and image.width == 480
        assert [x.id for x in image.characters] == [2]
        assert db.get(models.PixivJob, job_id).status == 'completed'
        assert Path(ImageService.image_full_path(image)).exists()
    assert not old.exists()


def test_distinct_keeps_both_and_records_only_selected_pair(waiting):
    context, _, _, old, _, _, worker = waiting
    assert decide(waiting, 'different').status_code == 202
    assert worker.run_once()
    with context() as db:
        assert db.query(models.Image).filter_by(file_status='available').count() == 2
        assert db.get(models.Image, 'AABBCCDDEE').pid is None
        new = db.query(models.Image).filter_by(pid='100_p0').one()
        assert [x.id for x in new.characters] == [1]
        assert db.query(models.DuplicatePairDecision).count() == 1
    assert old.exists()


def test_replacement_rollback_never_deletes_old_file(waiting, monkeypatch):
    context, _, _, old, job_id, _, worker = waiting
    assert decide(waiting, 'merge_new').status_code == 202
    def fail(*_args, **_kwargs):
        raise RuntimeError('simulated derivative job write failure')
    monkeypatch.setattr(jobs.ImageJobQueue, 'enqueue', fail)
    assert worker.run_once()
    assert old.exists()
    with context() as db:
        assert db.query(models.Image).count() == 1
        assert db.get(models.Image, 'AABBCCDDEE').file_status == 'available'
        assert db.query(models.PixivImageSource).count() == 0
        assert db.get(models.PixivJob, job_id).status == 'retry'


def test_stale_page_unknown_candidate_and_invalid_sources_are_rejected(waiting):
    assert decide(waiting, 'merge_new', page=1).status_code == 409
    assert decide(waiting, 'merge_new', image_id='FFFFFFFFFF').status_code == 409
    assert decide(waiting, 'merge_new', review_key='f'*32).status_code == 409
    assert decide(waiting, 'merge_new', metadata_sources={'characters':'unknown'}).status_code == 422


def test_changed_metadata_requires_fresh_review_and_double_submit_is_rejected(waiting):
    context, client, _, old, job_id, _, worker = waiting
    with context() as db:
        db.get(models.Image, 'AABBCCDDEE').description = 'changed while open'
    assert decide(waiting, 'merge_new').status_code == 409
    assert client.get(f'/api/pixiv-ol/imports/{job_id}/comparison').status_code == 409
    assert worker.run_once()
    with context() as db:
        result = db.get(models.PixivJob, job_id).result
    response = client.post(f'/api/pixiv-ol/imports/{job_id}/resolve', json={
        'action':'merge_existing','image_id':'AABBCCDDEE','page':0,'review_key':result['review_key']})
    assert response.status_code == 202
    assert client.post(f'/api/pixiv-ol/imports/{job_id}/resolve', json={'action':'different'}).status_code == 409
    assert old.exists()


def test_waiting_review_does_not_block_another_import(waiting, monkeypatch):
    context, client, _, _, job_id, _, worker = waiting
    class Provider(FakeProvider):
        def call(self, method, **kwargs):
            return {'illust': artwork(str(kwargs.get('illust_id', 200)))}
    monkeypatch.setattr(jobs.service, 'Provider', Provider)
    monkeypatch.setattr(jobs, 'download', lambda _url,path,**_kw:drawing(99).save(path,format='PNG'))
    response = client.post('/api/pixiv-ol/imports', json={'pid':'200','pages':[0],'group_ids':[1],'idempotency_key':'another_work'})
    assert worker.run_once()
    with context() as db:
        assert db.get(models.PixivJob, job_id).status == 'awaiting_duplicate'
        assert db.get(models.PixivJob, response.json()['id']).status == 'completed'


def test_review_is_private_and_owned(waiting):
    _, client, _, _, job_id, _, _ = waiting
    client.cookies.set('session_id','session-2')
    assert client.get(f'/api/pixiv-ol/imports/{job_id}/comparison').status_code == 409
    assert client.post(f'/api/pixiv-ol/imports/{job_id}/resolve',json={'action':'different'}).status_code == 409
    client.cookies.clear()
    assert client.get(f'/api/pixiv-ol/imports/{job_id}/comparison').status_code == 401


def test_older_direct_import_review_is_rebuilt_without_cart(waiting):
    context, client, _, _, job_id, _, worker = waiting
    with context() as db:
        job = db.get(models.PixivJob, job_id)
        job.result = {key: value for key, value in job.result.items()
                      if key not in ('incoming', 'review_key', 'candidate_signatures')}
    assert client.get(f'/api/pixiv-ol/imports/{job_id}/comparison').status_code == 409
    assert worker.run_once()
    result = client.get(f'/api/pixiv-ol/imports/{job_id}/comparison')
    assert result.status_code == 200
    assert result.json()['incoming']['pid'] == '100_p0'
