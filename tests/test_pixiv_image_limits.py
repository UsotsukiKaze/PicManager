import shutil

import pytest
from PIL import Image

from test_pixiv_ol import environment, install_fake, artwork
from app import models
from app.config import settings
from app.integrations.pixiv_ol import cart, jobs, service, viewer
from app.integrations.pixiv_ol.image_limits import open_image, pixel_limit
from app.integrations.pixiv_ol.provider import PixivError


@pytest.fixture
def large_original(tmp_path):
    path = tmp_path / '150364455_p0.jpg'
    # Actual problematic dimensions; grayscale keeps the test inexpensive.
    with Image.new('L', (6180, 9000), 128) as image:
        image.save(path, format='JPEG', quality=80)
    return path


def test_55_megapixel_original_survives_cache_read_and_offline_import(environment, monkeypatch, large_original):
    context, client, _ = environment
    install_fake(monkeypatch)
    monkeypatch.setattr(cart, 'download', lambda url, path, **kw: shutil.copyfile(large_original, path))
    monkeypatch.setattr(settings, 'PIXIV_MAX_IMAGE_PIXELS', 100_000_000)
    service.save_artworks('rev', [artwork()], 'recommended', 1)
    response = client.post('/api/pixiv-ol/cart', json={'pid': '100'})
    assert response.status_code == 202
    item_id = response.json()['id']
    assert jobs.Worker().run_once()
    with context() as db:
        item = db.get(models.PixivCartItem, item_id)
        assert item.status == 'ready'
        path = cart.cached_path(item, 0)
        assert item.cache['0']['width'] == 6180 and item.cache['0']['height'] == 9000
        assert viewer.image_type(path) == 'image/jpeg'
        assert path.read_bytes() == large_original.read_bytes()
        with Image.open(cart.directory(item_id) / 'preview.webp') as image:
            assert max(image.size) <= 800
    monkeypatch.setattr(service, 'client_for_job', lambda *a: pytest.fail('Cached import must stay offline'))
    assert client.post('/api/pixiv-ol/cart/imports', json={'item_ids': [item_id]}).status_code == 202
    assert jobs.Worker().run_once()
    with context() as db:
        image = db.query(models.Image).one()
        assert (image.width, image.height) == (6180, 9000)
        assert db.query(models.PixivJob).filter_by(kind='import').one().status == 'completed'


def test_configured_pixel_guard_applies_to_cart_and_reader(monkeypatch, large_original):
    monkeypatch.setattr(settings, 'PIXIV_MAX_IMAGE_PIXELS', 50_000_000)
    for inspect in (cart.inspect_image, viewer.image_type):
        with pytest.raises(PixivError, match='image_too_large'):
            inspect(large_original)


def test_pixel_configuration_cannot_remove_the_upper_bound(monkeypatch):
    monkeypatch.setattr(settings, 'PIXIV_MAX_IMAGE_PIXELS', 999_000_000)
    assert pixel_limit() == 100_000_000


def test_pillow_bomb_is_reported_as_size_rejection(monkeypatch):
    def reject(*args):
        raise Image.DecompressionBombError('oversized header')
    monkeypatch.setattr(Image, 'open', reject)
    with pytest.raises(PixivError, match='image_too_large'):
        with open_image('oversized'):
            pytest.fail('Must not decode the oversized image')
