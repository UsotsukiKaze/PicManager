from pathlib import Path
from datetime import datetime

import pytest
from PIL import Image
from test_pixiv_ol import environment as environment, artwork
from app import models, local_check
from app.config import settings
from app.tag_mappings import CachedImageTagCheck, save_mapping
from app.integrations.pixiv_ol import service


@pytest.fixture
def library(environment, monkeypatch):
    context, client, root = environment
    for attr in ('THUMB_PATH', 'PREVIEW_PATH'):
        monkeypatch.setattr(settings, attr, str(root/attr.lower()))
    store = Path(settings.STORE_PATH)
    store.mkdir(parents=True)
    path = store/'0011223344.png'
    Image.new('RGB', (40, 30), 'red').save(path)
    with context() as db:
        db.add(models.Group(id=2, name='另一分组'))
        db.add_all([models.Character(id=10, name='甲', group_id=1), models.Character(id=11, name='乙', group_id=2),
                    models.FeatureTag(id=2, name='短发')])
        db.flush()
        image = models.Image(image_id='0011223344', pid='100_p0', file_path=str(path), file_extension='png',
                             pixiv_checked_at=datetime(2026, 1, 1))
        image.groups = [db.get(models.Group, 1)]
        image.characters = [db.get(models.Character, 10)]
        image.pixiv_metadata = models.PixivImageMetadata(work_id='100', page_index=0, page_count=2,
            tags=[{'name':'甲'}, {'name':'乙'}, {'name':'白髪'}], status='verified', validated_at=datetime(2026, 1, 1))
        db.add(image)
    return context, client, path


def test_local_check_adds_features_and_bindings_but_preserves_multipage_labels(library):
    context, _, _ = library
    with context() as db:
        result = local_check.run_batch(db, incremental=True)
        assert result['ready'] == 1 and result['tag_updated'] == 1
        assert result['tag_mappings_created'] == 2 and result['tag_pending'] == 1
    with context() as db:
        image = db.get(models.Image, '0011223344')
        assert [row.id for row in image.groups] == [1]
        assert [row.id for row in image.characters] == [10]
        assert {row.name for row in image.feature_tags} == {'白发', 'Pixiv'}
        assert image.pixiv_checked_at == image.pixiv_metadata.validated_at == datetime(2026, 1, 1)
        assert image.local_checked_at is None  # Duplicate review still owns the completion marker.
        assert db.query(models.PixivTagMapping).filter_by(target_type='feature', target_id=1).one().original_tag == '白髪'
        assert local_check.run_batch(db)['tag_updated'] == 0
        assert db.query(models.PixivTagMapping).count() == 2


def test_scoped_feature_mapping_uses_existing_image_group_without_pixiv_group_tag(library):
    context, _, _ = library
    with context() as db:
        image = db.get(models.Image, '0011223344')
        image.pixiv_metadata.tags = [{'name':'发色'}]
        save_mapping(db, '发色', 'feature', 2, context=2)
        save_mapping(db, '发色', 'feature', 1, context=1)
        db.delete(db.get(models.PixivAccount, 1))
        assert CachedImageTagCheck(db).check(image)['tag_pending'] == 0
        assert 1 in {row.id for row in image.feature_tags} and 2 not in {row.id for row in image.feature_tags}


def test_ambiguous_contexts_and_manual_ignore_do_not_guess_or_override(library):
    context, _, _ = library
    with context() as db:
        image = db.get(models.Image, '0011223344')
        image.groups.append(db.get(models.Group, 2))
        image.pixiv_metadata.tags = [{'name':'发色'}, {'name':'白髪'}]
        save_mapping(db, '发色', 'feature', 1, context=1)
        save_mapping(db, '发色', 'feature', 2, context=2)
        save_mapping(db, '白髪', 'ignore', None)
        result = CachedImageTagCheck(db).check(image)
        assert result['tag_pending'] == 1 and result['tag_mappings_created'] == 0
        assert {row.name for row in image.feature_tags} == {'Pixiv'}
        assert db.query(models.PixivTagMapping).filter_by(normalized_tag='白髪').one().target_type == 'ignore'


def test_single_page_only_fills_an_empty_unambiguous_role_selection(library):
    context, _, _ = library
    with context() as db:
        image = db.get(models.Image, '0011223344')
        image.characters = []
        image.pixiv_metadata.page_count = 1
        image.pixiv_metadata.tags = [{'name':'甲'}]
        assert CachedImageTagCheck(db).check(image)['tag_updated'] == 1
        assert [row.id for row in image.characters] == [10]
        image.pixiv_metadata.tags = [{'name':'乙'}]
        assert CachedImageTagCheck(db).check(image)['tag_pending'] == 1
        assert [row.id for row in image.characters] == [10]


def test_legacy_empty_tags_are_repaired_from_snapshot_without_network(library, monkeypatch):
    context, _, _ = library
    monkeypatch.setattr(service, 'client_for_job', lambda *_:pytest.fail('local validation must never fetch Pixiv'))
    with context() as db:
        image = db.get(models.Image, '0011223344')
        image.pixiv_metadata.tags = []
        art = service.normalize_artwork(artwork(tags=[{'name':'白髪'}], pages=2))
        db.add(models.PixivArtwork(account_revision='rev', pid='100', author_id='9', title='cache',
                                  published_at=datetime(2026, 1, 1), metadata_json=art, origins=[]))
        db.flush()
        result = CachedImageTagCheck(db).check(image)
        assert result['tag_updated'] == 1 and image.pixiv_metadata.tags == [{'name':'白髪', 'translated_name':None}]
        assert {row.name for row in image.feature_tags} == {'白发', 'Pixiv'}
        assert image.pixiv_checked_at == datetime(2026, 1, 1)


def test_changed_or_unavailable_content_does_not_reapply_stale_tags(library):
    context, _, _ = library
    with context() as db:
        image = db.get(models.Image, '0011223344')
        image.perceptual_hash = 'ffffffffffffffff'
        result = local_check.run_batch(db)
        assert result['ready'] == 1 and result['tag_checked'] == 0
        assert image.pixiv_metadata is None and not image.feature_tags
        assert image.pixiv_checked_at is None


def test_unavailable_metadata_does_not_supply_tags(library):
    context, _, _ = library
    with context() as db:
        image = db.get(models.Image, '0011223344')
        image.pixiv_metadata.status = 'unavailable'
        assert CachedImageTagCheck(db).check(image)['tag_checked'] == 0
        assert not image.feature_tags
