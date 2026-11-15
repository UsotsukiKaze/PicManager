from datetime import datetime, timedelta
from pathlib import Path

import pytest
from PIL import Image, ImageDraw

from test_pixiv_ol import environment, artwork
from test_temp_pixiv import temp_environment, create_file, check_file, upload_data
from test_pixiv_check_queue import queued, client_factory, drain
from app import models, pixiv_quality, pixiv_check_queue
from app.config import settings
from app.integrations.pixiv_ol import service, viewer
from app.integrations.pixiv_ol.provider import PixivError
from app.pixiv_metadata import apply_metadata, public_metadata
from app.services import ImageService


@pytest.fixture(autouse=True)
def derivatives(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, 'THUMB_PATH', str(tmp_path/'thumbs'))
    monkeypatch.setattr(settings, 'PREVIEW_PATH', str(tmp_path/'previews'))


def original(temp, monkeypatch, size=(160, 100)):
    path = temp.parent/'canonical.png'
    Image.new('RGB', size, 'blue').save(path)
    monkeypatch.setattr(viewer, 'original', lambda *_: (path, 'image/png'))
    return path


def test_temp_precheck_advertises_upgrade_and_imports_actual_original(temp_environment, monkeypatch):
    context, client, temp, _, _ = temp_environment
    remote = original(temp, monkeypatch)
    create_file(temp)
    _, checked = check_file(client)
    assert checked.json()['quality']['status'] == 'upgrade'
    result = client.post('/api/upload/temp', json=upload_data(checked))
    assert result.status_code == 200, result.text
    with context() as db:
        image = db.get(models.Image, result.json()['image_id'])
        assert (image.width, image.height) == (160, 100)
        assert Path(ImageService.image_full_path(image)).read_bytes() == remote.read_bytes()
        assert public_metadata(image)['pixiv_status'] == 'complete'
        assert [row.id for row in image.characters] == [1]
    assert not (temp/'12345678_p1.png').exists()


def test_original_failure_never_loses_temp_or_marks_quality_complete(temp_environment, monkeypatch):
    context, client, temp, _, _ = temp_environment
    create_file(temp)
    def unavailable(*_):
        raise PixivError('download_failed')
    monkeypatch.setattr(viewer, 'original', unavailable)
    _, checked = check_file(client)
    assert checked.status_code == 200
    result = client.post('/api/upload/temp', json=upload_data(checked))
    assert result.status_code == 502
    assert (temp/'12345678_p1.png').exists()
    with context() as db:
        assert db.query(models.Image).count() == 0


def test_metadata_match_is_not_quality_completion_and_file_edits_invalidate_completion(temp_environment):
    context, client, temp, _, _ = temp_environment
    create_file(temp, 'manual.png')
    result = client.post('/api/upload/temp', json={'filename':'manual.png','character_ids':[1],'group_ids':[1]})
    image_id = result.json()['image_id']
    art = service.normalize_artwork(artwork('12345678'))
    with context() as db:
        image = db.get(models.Image, image_id)
        assert public_metadata(image)['pixiv_status'] == 'unchecked'
        apply_metadata(db, image, art, 0)
    with context() as db:
        image = db.get(models.Image, image_id)
        assert public_metadata(image)['pixiv_status'] == 'matched'
        image.pixiv_quality_checked_at = datetime.utcnow()
    with context() as db:
        image = db.get(models.Image, image_id)
        assert public_metadata(image)['pixiv_status'] == 'complete'
        image.file_size += 1
    with context() as db:
        assert public_metadata(db.get(models.Image, image_id))['pixiv_status'] == 'matched'


@pytest.mark.parametrize('size,upgraded', [((240, 150), True), ((40, 25), False)])
def test_temp_duplicate_linked_library_keeps_identity_and_best_file(temp_environment, monkeypatch, size, upgraded):
    context, client, temp, _, _ = temp_environment
    original(temp, monkeypatch)
    create_file(temp)
    _, checked = check_file(client)
    saved = client.post('/api/upload/temp', json=upload_data(checked)).json()['image_id']
    Image.new('RGB', size, 'blue').save(temp/'copy.png')
    scan = client.post('/api/upload/temp-duplicates/scan?limit=1').json()['matches'][0]
    assert scan['auto_resolve'] is True
    result = client.post('/api/upload/temp-duplicates/auto', json={'token':scan['duplicate_token']})
    assert result.status_code == 200, result.text
    assert result.json()['image_id'] == saved
    assert not (temp/'copy.png').exists()
    with context() as db:
        assert db.query(models.Image).count() == 1
        image = db.get(models.Image, saved)
        assert image.pid == '12345678_p1' and image.pixiv_metadata
        assert [row.id for row in image.characters] == [1]
        assert (image.width, image.height) == (size if upgraded else (160, 100))
        assert public_metadata(image)['pixiv_status'] == ('matched' if upgraded else 'complete')


def test_incoming_pixiv_without_library_association_requires_review(temp_environment):
    _, client, temp, _, _ = temp_environment
    create_file(temp, 'manual.png')
    client.post('/api/upload/temp', json={'filename':'manual.png','character_ids':[1],'group_ids':[1]})
    create_file(temp)
    scan = client.post('/api/upload/temp-duplicates/scan?limit=1').json()['matches'][0]
    assert scan['auto_resolve'] is False
    result = client.post('/api/upload/temp-duplicates/auto', json={'token':scan['duplicate_token']})
    assert result.status_code == 409
    assert (temp/'12345678_p1.png').exists()


def test_comparison_prefers_canonical_equal_dimensions_but_rejects_other_picture(tmp_path):
    local, remote = tmp_path/'local.png', tmp_path/'remote.png'
    image = Image.new('RGB', (160, 100), 'white')
    ImageDraw.Draw(image).rectangle((0, 0, 80, 100), fill='black')
    image.save(remote)
    image.save(local, compress_level=0)
    assert pixiv_quality.compare(local, remote)['replace'] is True
    image.transpose(Image.Transpose.FLIP_LEFT_RIGHT).save(local)
    assert pixiv_quality.compare(local, remote)['matched'] is False


def test_recent_quality_queue_limits_images_and_replaces_automatically(queued, monkeypatch):
    context, client, add = queued
    add(3)
    client_factory(monkeypatch)
    with context() as db:
        for index, image in enumerate(db.query(models.Image).order_by(models.Image.image_id)):
            image.created_at = datetime(2026, 1, 1)+timedelta(days=index)
    path = Path(settings.TEMP_PATH).parent/'canonical.png'
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new('RGB', (320, 200), 'red').save(path)
    monkeypatch.setattr(viewer, 'original', lambda *_: (path, 'image/png'))
    result = client.post('/api/system/pixiv-check/queue?mode=quality&limit=1&auto_upgrade=true')
    assert result.status_code == 200, result.text
    drain(pixiv_check_queue.PixivCheckWorker())
    with context() as db:
        latest = db.get(models.Image, '0000000003')
        assert (latest.width, latest.height) == (320, 200)
        assert public_metadata(latest)['pixiv_status'] == 'complete'
        assert db.get(models.Image, '0000000001').pixiv_checked_at is None
        assert db.query(models.PixivCheckItem).count() == 1
