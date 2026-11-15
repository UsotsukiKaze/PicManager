from io import BytesIO

from PIL import Image, ImageChops, ImageOps

from app import card_art


def test_lossless_art_matches_renderer_and_invalidates(tmp_path, monkeypatch):
    monkeypatch.setattr(card_art.settings, 'DATA_PATH', str(tmp_path))
    path = tmp_path / 'original.png'
    source = Image.effect_noise((1800, 2400), 50).convert('RGB')
    source.save(path)
    expected = ImageOps.exif_transpose(source).convert('RGB')
    expected.thumbnail((896, 1280), Image.Resampling.LANCZOS)
    original = path.read_bytes()
    payload = card_art.artwork(path)
    assert ImageChops.difference(Image.open(BytesIO(payload)), expected).getbbox() is None
    assert path.read_bytes() == original
    assert card_art.artwork(path) == payload
    old_revision = card_art.revision(path)
    Image.new('RGB', (400, 600), 'blue').save(path)
    assert card_art.revision(path) != old_revision
    assert card_art.artwork(path) != payload


def test_disk_cache_stays_within_budget(tmp_path, monkeypatch):
    monkeypatch.setattr(card_art.settings, 'DATA_PATH', str(tmp_path))
    monkeypatch.setattr(card_art, 'MAX_BYTES', 1)
    path = tmp_path / 'original.png'
    Image.new('RGB', (100, 100), 'red').save(path)
    assert card_art.artwork(path)
    assert not list((tmp_path / 'card-art-cache').glob('*.png'))


def test_preview_selection_checks_size_freshness_and_integrity(tmp_path):
    import os
    source, preview = tmp_path/'original.png', tmp_path/'preview.webp'
    Image.new('RGB', (1800, 2400), 'red').save(source)
    Image.new('RGB', (1200, 1600), 'red').save(preview)
    assert card_art.existing_preview(source, preview, 1800, 2400) == preview.read_bytes()
    os.utime(preview, (1, 1))
    assert card_art.existing_preview(source, preview, 1800, 2400) is None
    Image.new('RGB', (300, 400), 'red').save(preview)
    assert card_art.existing_preview(source, preview, 1800, 2400) is None
    preview.write_bytes(b'broken')
    assert card_art.existing_preview(source, preview, 1800, 2400) is None
