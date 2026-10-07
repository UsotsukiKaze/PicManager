from copy import deepcopy

import pytest
from test_pixiv_ol import environment as environment, artwork, install_fake, FakeProvider
from app import models
from app.integrations.pixiv_ol import service, jobs


@pytest.fixture
def cart_env(environment, monkeypatch):
    context, client, root = environment
    install_fake(monkeypatch)
    with context() as db:
        db.add_all([models.FeatureTag(id=2, name='新映射'), models.FeatureTag(id=3, name='手动标签'),
                    models.Character(id=10, name='角色甲', group_id=1), models.Character(id=11, name='角色乙', group_id=1)])
    assert client.post('/api/pixiv-ol/tag-mappings', json={'tag':'外部特征','target_type':'feature','target_id':1}).status_code == 200
    return context, client, root


def add_cart(cart_env, *, split=False):
    _, client, _ = cart_env
    raw = artwork(tags=[{'name':'游戏'}, {'name':'外部特征'}, {'name':'角色甲'}], pages=2 if split else 1)
    service.save_artworks('rev', [raw], 'recommended', 1)
    response = client.post('/api/pixiv-ol/cart', json={'pid':'100','import_mode':'split' if split else 'merged'})
    assert response.status_code == 202
    return response.json()


def remap(client, target=2):
    assert client.post('/api/pixiv-ol/tag-mappings', json={'tag':'外部特征','target_type':'feature','target_id':target}).status_code == 200


def refresh(client):
    response = client.post('/api/pixiv-ol/cart/refresh-tags')
    assert response.status_code == 200
    return response.json()['items'][0]


def test_refresh_updates_auto_tags_and_reading_does_not_mutate(cart_env, monkeypatch):
    context, client, _ = cart_env
    row = add_cart(cart_env)
    remap(client)
    assert client.get('/api/pixiv-ol/cart').json()['items'][0]['draft'] == row['draft']
    monkeypatch.setattr(service, 'client_for_job', lambda *_:pytest.fail('tag refresh must stay offline'))
    updated = refresh(client)
    assert updated['draft']['feature_tag_ids'] == [2]
    assert updated['draft']['character_ids'] == [10]
    assert refresh(client)['draft'] == updated['draft']
    with context() as db:
        assert db.get(models.PixivCartItem, row['id']).draft == updated['draft']


def test_refresh_preserves_manual_additions_and_removals(cart_env):
    _, client, _ = cart_env
    row = add_cart(cart_env)
    assert client.put(f"/api/pixiv-ol/cart/{row['id']}", json={'pages':[0],'group_ids':[1],'character_ids':[11],'feature_tag_ids':[3]}).status_code == 200
    unchanged = refresh(client)['draft']
    assert unchanged['feature_tag_ids'] == [3]
    assert unchanged['character_ids'] == [11]
    remap(client)
    updated = refresh(client)['draft']
    assert updated['feature_tag_ids'] == [2, 3]
    assert updated['character_ids'] == [11]
    assert updated['age_rating'] == 'r12'


def test_split_refresh_keeps_confirmed_page_roles_and_independent_manual_tags(cart_env):
    _, client, _ = cart_env
    row = add_cart(cart_env, split=True)
    assert client.put(f"/api/pixiv-ol/cart/{row['id']}/pages/0", json={'group_ids':[1],'character_ids':[11],'feature_tag_ids':[3]}).status_code == 200
    remap(client)
    updated = refresh(client)['draft']
    assert updated['confirmed_pages'] == [0]
    assert updated['pages'] == [0, 1]
    assert updated['page_drafts']['0']['character_ids'] == [11]
    assert updated['page_drafts']['0']['feature_tag_ids'] == [2, 3]
    assert updated['page_drafts']['1']['feature_tag_ids'] == [2]
    assert updated['page_drafts']['1']['character_ids'] == [10]


def test_deleted_mapping_removes_only_auto_tags(cart_env):
    _, client, _ = cart_env
    row = add_cart(cart_env)
    mapping = next(row for row in client.get('/api/pixiv-ol/tag-mappings').json() if row['tag'] == '外部特征')
    assert client.delete(f"/api/pixiv-ol/tag-mappings/{mapping['id']}").status_code == 200
    assert refresh(client)['draft']['feature_tag_ids'] == []
    assert client.put(f"/api/pixiv-ol/cart/{row['id']}", json={'pages':[0],'group_ids':[1],'feature_tag_ids':[1]}).status_code == 200
    assert refresh(client)['draft']['feature_tag_ids'] == [1]


def test_legacy_drafts_preserve_existing_labels_and_accept_missing_features(cart_env):
    context, client, _ = cart_env
    row = add_cart(cart_env)
    with context() as db:
        item = db.get(models.PixivCartItem, row['id'])
        item.draft = {key:value for key,value in item.draft.items() if key != '_tag_refresh'}
    remap(client)
    assert refresh(client)['draft']['feature_tag_ids'] == [1, 2]


def test_importing_cart_and_job_payload_are_not_changed(cart_env):
    context, client, _ = cart_env
    row = add_cart(cart_env)
    with context() as db:
        item = db.get(models.PixivCartItem, row['id'])
        item.status = 'importing'
        before = deepcopy(item.draft)
    remap(client)
    assert refresh(client)['draft'] == before


def test_refresh_uses_page_group_context(cart_env):
    context, client, _ = cart_env
    add_cart(cart_env)
    with context() as db:
        db.add(models.Group(id=2, name='另一分组'))
    assert client.post('/api/pixiv-ol/tag-mappings', json={'tag':'外部特征','target_type':'feature','target_id':2,'group_context':2}).status_code == 200
    assert refresh(client)['draft']['feature_tag_ids'] == [1]


def test_refresh_requires_admin_ownership_and_write_guard(cart_env):
    _, client, _ = cart_env
    add_cart(cart_env)
    client.headers.pop('X-Pixiv-OL')
    assert client.post('/api/pixiv-ol/cart/refresh-tags').status_code == 403
    client.headers['X-Pixiv-OL'] = '1'
    client.cookies.set('session_id','session-2')
    assert client.post('/api/pixiv-ol/cart/refresh-tags').json()['items'] == []
    client.cookies.set('session_id','session-3')
    assert client.post('/api/pixiv-ol/cart/refresh-tags').status_code == 403


def test_import_uses_refreshed_tags_offline(cart_env, monkeypatch):
    context, client, _ = cart_env
    row = add_cart(cart_env)
    raw = artwork(tags=[{'name':'游戏'}, {'name':'外部特征'}, {'name':'角色甲'}])
    class MatchingProvider(FakeProvider):
        def __init__(self, token):
            super().__init__(token)
            self.raw = raw
    monkeypatch.setattr(service, 'Provider', MatchingProvider)
    assert jobs.Worker().run_once()
    remap(client)
    assert refresh(client)['draft']['feature_tag_ids'] == [2]
    assert client.post('/api/pixiv-ol/cart/imports', json={'item_ids':[row['id']]}).status_code == 202
    assert jobs.Worker().run_once()
    with context() as db:
        image = db.query(models.Image).one()
        assert {tag.name for tag in image.feature_tags} == {'新映射', 'Pixiv'}
