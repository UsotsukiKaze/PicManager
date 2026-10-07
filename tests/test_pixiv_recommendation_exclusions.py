import pytest

from test_pixiv_ol import environment as environment, artwork
from app import models
from app.integrations.pixiv_ol import service
from app.integrations.pixiv_ol.recommendations import rank_candidates


def batch(db, mode='combined', size=8):
    items = [service.normalize_artwork(artwork(str(100 + n), pages=3)) for n in range(size)]
    db.add(models.PixivRecommendationBatch(id=mode, account_revision='rev', mode=mode, items=items, profile={}))


def cart(db, pid, *, actor=1, revision='rev', status='ready'):
    row = models.PixivCartItem(id=f'{revision}-{actor}-{pid}', account_revision=revision,
                               actor_id=actor, pid=pid, status=status, pages=[0],
                               metadata_json=service.normalize_artwork(artwork(pid)))
    db.add(row)
    return row


def local(db, pid, *, id_='0000000001'):
    db.add(models.Image(image_id=id_, pid=pid, file_extension='png', file_path='fixture.png'))


def get(client, mode='combined', **params):
    response = client.get('/api/pixiv-ol/recommendations', params={'mode':mode, 'batch_id':mode, **params})
    assert response.status_code == 200
    return response.json()


@pytest.mark.parametrize('mode', ['combined', 'native'])
def test_cached_recommendations_filter_library_and_own_cart_before_paginating(environment, mode):
    context, client, _ = environment
    with context() as db:
        batch(db, mode)
        local(db, '100_p2')
        cart(db, '101', status='pending')
        cart(db, '102', status='failed')
        cart(db, '103', status='importing')
        cart(db, '104', actor=2)
        cart(db, '105', revision='old')
    result = get(client, mode, limit=2)
    assert [item['pid'] for item in result['items']] == ['104', '105']
    assert result['total'] == 4 and result['next_offset'] == 6 and result['has_more']
    assert all(item['imported_pages'] == [] and 'originals' not in item for item in result['items'])
    client.cookies.set('session_id', 'session-2')
    assert [item['pid'] for item in get(client, mode)['items']] == ['101', '102', '103', '105', '106', '107']


def test_importing_or_adding_earlier_cards_does_not_skip_unseen_cards(environment):
    context, client, _ = environment
    with context() as db:
        batch(db)
    first = get(client, limit=3)
    assert [item['pid'] for item in first['items']] == ['100', '101', '102']
    with context() as db:
        local(db, '100_p0')
        cart(db, '101')
        cart(db, '103')
    next_ = get(client, offset=first['next_offset'], limit=3)
    assert [item['pid'] for item in next_['items']] == ['104', '105', '106']
    assert next_['next_offset'] == 7 and next_['has_more']
    last = get(client, offset=next_['next_offset'], limit=3)
    assert [item['pid'] for item in last['items']] == ['107'] and not last['has_more']


def test_removed_cart_item_returns_to_cached_batch_and_full_page_is_filled(environment):
    context, client, _ = environment
    with context() as db:
        batch(db)
        cart(db, '100')
        cart(db, '102')
        cart(db, '104')
    result = get(client, limit=3)
    assert [item['pid'] for item in result['items']] == ['101', '103', '105']
    with context() as db:
        db.delete(db.get(models.PixivCartItem, 'rev-1-100'))
    result = get(client, limit=3)
    assert [item['pid'] for item in result['items']] == ['100', '101', '103']


def test_no_visible_cards_exhausts_batch_without_stalling_cursor(environment):
    context, client, _ = environment
    with context() as db:
        batch(db, size=2)
        cart(db, '100')
        local(db, '101_p1')
    result = get(client)
    assert result['items'] == [] and result['total'] == 0
    assert result['next_offset'] == 2 and not result['has_more']


@pytest.mark.parametrize('mode', ['combined', 'native'])
def test_ranking_excludes_partial_library_works_but_leaves_shared_cart_filter_to_reader(environment, mode):
    context, _, _ = environment
    service.save_artworks('rev', [artwork('100', pages=3), artwork('101')], 'recommended', 1,
                           ranks=True, source_batch='source')
    with context() as db:
        local(db, '100_p2')
        cart(db, '101')
        account = db.get(models.PixivAccount, 1)
        account.sync_state = {'recommended':{'batch':'source'}, 'candidate_batch':'source'}
        items, _ = rank_candidates(db, account, mode)
        assert [item['pid'] for item in items] == ['101']
