from collections import Counter
from types import SimpleNamespace

import pytest

from test_pixiv_ol import environment, artwork, FakeProvider
from test_pixiv_recommendation_preferences import mapping, image, like, cached
from app import models
from app.integrations.pixiv_ol import service, strategies, jobs
from app.integrations.pixiv_ol.recommendations import TagIndex, rank_candidates


def roles(db):
    db.add_all([models.Character(id=10, name='热门', group_id=1),
                models.Character(id=11, name='冷门', group_id=1)])
    db.flush()
    mapping(db, 'GameNative', 'group', 1)
    mapping(db, 'PopularNative', 'character', 10, 1)
    mapping(db, 'RareNative', 'character', 11, 1)
    mapping(db, 'WhiteNative', 'feature', 1)
    for n in range(55):
        image(db, f'{n + 1:010d}', str(1000 + n), role=10 if n < 50 else 11, features=[1])
    db.flush()


@pytest.mark.parametrize('channel', ['likes', 'cart', 'library'])
def test_personal_learns_native_tags_from_each_channel(environment, channel):
    context, _, _ = environment
    with context() as db:
        art = cached(db, '800', ['Atmosphere'])
        if channel == 'likes':
            like(db, '800')
        elif channel == 'cart':
            db.add(models.PixivCartItem(id='cart', actor_id=1, account_revision='rev', pid='800',
                                       pages=[0], metadata_json=art))
        else:
            image(db, '0000000001', '800_p0')
            db.add(models.PixivImageMetadata(image_id='0000000001', work_id='800', page_index=0,
                                             page_count=1, tags=[{'name':'Atmosphere'}]))
        cached(db, '801', ['Other'])
        cached(db, '802', ['Atmosphere'])
        db.flush()
        items, profile = rank_candidates(db, db.get(models.PixivAccount, 1), 'personal')
        assert profile['vectors']['raw']['atmosphere'] > 0
        assert next(n for n, row in enumerate(items) if row['pid'] == '802') < next(n for n, row in enumerate(items) if row['pid'] == '801')
        assert all(row['reasons'] == [] for row in items)


def test_stock_counts_groups_and_roles_independently_and_never_uses_favorite_roles(environment):
    context, _, _ = environment
    with context() as db:
        roles(db)
        db.add(models.Group(id=2, name='大组'))
        db.flush()
        for n in range(275):
            db.add(models.Image(image_id=f'{n + 100:010d}', file_extension='png', file_path='fixture', groups=[db.get(models.Group, 2)]))
        cached(db, '800', ['GameNative', 'PopularNative', 'WhiteNative'])
        like(db, '800')
        db.get(models.PixivAccount, 1).preferences = {}
        db.flush()
        index = TagIndex(db)
        account = db.get(models.PixivAccount, 1)
        stock = strategies.build_profile(db, index, account, 'stock')
        assert stock['quotas'][1] / stock['quotas'][2] == pytest.approx(5)
        assert stock['character_quotas'][1][11] / stock['character_quotas'][1][10] == pytest.approx(10)
        db.query(models.PixivFeedback).delete()
        db.flush()
        no_likes = strategies.build_profile(db, index, account, 'stock')
        assert stock['quotas'] == no_likes['quotas']
        assert stock['character_quotas'] == no_likes['character_quotas']
        assert stock['liked_raw_global'] == {}


def test_personal_deduplicates_multi_page_work_and_has_no_inverse_inventory_weights(environment):
    context, _, _ = environment
    with context() as db:
        roles(db)
        account, index = db.get(models.PixivAccount, 1), TagIndex(db)
        before = strategies.build_profile(db, index, account, 'personal')
        image(db, '0000000999', '1000_p1', role=10, features=[1])
        db.flush()
        after = strategies.build_profile(db, index, account, 'personal')
        assert after['vectors'] == before['vectors']
        assert after['quotas'] == before['quotas']
        assert after['algorithm'] != strategies.build_profile(db, index, account, 'stock')['algorithm']


def stock_fixture(known=400, unknown_role=50, unknown_group=50):
    index = SimpleNamespace(characters={10:SimpleNamespace(group_id=1), 11:SimpleNamespace(group_id=1), 20:SimpleNamespace(group_id=2)})
    profile = {'quotas':{1:5/6, 2:1/6}, 'inventory':{1:55, 2:275},
               'character_inventory':{10:50, 11:5, 20:275},
               'character_quotas':{1:{10:1/11, 11:10/11}, 2:{20:1}}}
    items = []
    def add(groups, roles_):
        n = len(items)
        items.append({'pid':str(n), 'author_id':str(n), '_score':1,
                      'match':{'group_ids':groups, 'character_ids':roles_, 'conflicts':[]}})
    for n in range(known):
        role = (10, 11, 20)[n % 3]
        add([index.characters[role].group_id], [role])
    for _ in range(unknown_role):
        add([1], [])
    for _ in range(unknown_group):
        add([], [])
    return items, profile, index


def test_stock_reserves_independent_15_and_5_percent_and_balances_both_levels():
    items, profile, index = stock_fixture()
    result = strategies.stock_schedule(items, profile, index)
    assert Counter(row['stock_pool'] for row in result) == {'known':144, 'new_character':27, 'new_group':9}
    for offset in range(0, 180, 20):
        assert Counter(row['stock_pool'] for row in result[offset:offset + 20]) == {'known':16, 'new_character':3, 'new_group':1}
    counts = Counter(row.get('primary_character') for row in result)
    assert counts[11] > 8 * counts[10]
    groups = Counter(row.get('primary_group') for row in result if row['stock_pool'] == 'known')
    assert groups[1] == 5 * groups[2]


@pytest.mark.parametrize('sizes', [(400, 50, 0), (10, 100, 100), (0, 100, 100)])
def test_stock_does_not_fill_missing_supply_with_excess_exploration(sizes):
    items, profile, index = stock_fixture(*sizes)
    result = strategies.stock_schedule(items, profile, index)
    counts = Counter(row['stock_pool'] for row in result)
    assert counts['new_character'] <= int(len(result) * .15)
    assert counts['new_group'] <= int(len(result) * .05)


def test_stock_live_filtering_caps_exploration_and_keeps_original_positions():
    rows = [(n, {'stock_pool':'new_character' if n < 15 else 'new_group' if n < 20 else 'known'}) for n in range(100)]
    page = strategies.stock_page(rows, 20)
    assert Counter(item['stock_pool'] for _, item in page) == {'known':16, 'new_character':3, 'new_group':1}
    assert page[-1][0] == 35
    assert strategies.stock_page(rows[:20], 20) == []


def test_stock_never_treats_disabled_known_groups_or_ambiguous_tags_as_new_groups():
    items, profile, index = stock_fixture()
    items += [{'pid':'disabled', 'author_id':'9', '_score':99, 'match':{'group_ids':[3], 'character_ids':[], 'conflicts':[]}},
              {'pid':'conflict', 'author_id':'9', '_score':99, 'match':{'group_ids':[1], 'character_ids':[], 'conflicts':['ambiguous']}}]
    assert not {'disabled', 'conflict'} & {row['pid'] for row in strategies.stock_schedule(items, profile, index)}


def test_search_plans_use_rare_role_mappings_and_unanchored_features(environment):
    context, _, _ = environment
    with context() as db:
        roles(db)
        account, index = db.get(models.PixivAccount, 1), TagIndex(db)
        stock = strategies.build_profile(db, index, account, 'stock')
        plan = strategies.search_plan(db, index, stock, account.preferences, 'stock', 0)
        words = [row['word'] for row in plan]
        assert words.index('RareNative') < words.index('PopularNative')
        assert any(row['word'] == 'WhiteNative' and row['group'] is None for row in plan)
        assert len(plan) <= 20
        assert strategies.search_plan(db, index, {}, {}, 'discovery', 0) == []


def test_first_stock_visit_warms_one_rare_role_query_and_defers_remaining_searches(environment):
    context, _, _ = environment
    with context() as db:
        roles(db)
    class Remote(FakeProvider):
        def __init__(self):
            self.calls = []
        def call(self, method, **params):
            self.calls.append((method, params))
            tags = ['GameNative','RareNative'] if method == 'search_illust' else ['GameNative','PopularNative']
            return {'illusts':[artwork(str(800 + len(self.calls)), [{'name':tag} for tag in tags])], 'next_url':None}
    remote = Remote()
    # Entering a mode starts through /browse, before any manual refresh.
    result = service.refresh_candidates(remote, 'rev', 1, 'stock', continuation=True, progressive=True)
    assert [method for method, _ in remote.calls] == ['illust_recommended','search_illust']
    assert remote.calls[1][1]['word'] == 'RareNative'
    assert result['more'] is True
    with context() as db:
        state = db.get(models.PixivAccount, 1).sync_state['recommendation_stream_stock_1']
        assert state['deferred_queries']
        assert 'RareNative' not in [row['word'] for row in state['deferred_queries']]


def test_discovery_preserves_native_order_and_modes_keep_their_own_cursor_and_batches(environment):
    context, client, _ = environment
    class Remote(FakeProvider):
        def call(self, method, **params):
            assert method == 'illust_recommended'
            offset = int(params.get('offset', 0))
            return {'illusts':[artwork(str(900 + offset), [{'name':'游戏'}]), artwork(str(901 + offset), [{'name':'白发'}])],
                    'next_url':f'https://app-api.pixiv.net/v1/illust/recommended?offset={offset + 2}'}
    remote = Remote('test')
    first = service.refresh_candidates(remote, 'rev', 1, 'discovery', progressive=True)
    service.refresh_candidates(remote, 'rev', 1, 'personal', progressive=True)
    second = service.refresh_candidates(remote, 'rev', 1, 'discovery', continuation=True, progressive=True, seen_pids=['900', '901'])
    path = '/api/pixiv-ol/recommendations?mode=discovery&batch_id='
    assert [row['pid'] for row in client.get(path + first['batch_id']).json()['items']] == ['900', '901']
    assert [row['pid'] for row in client.get(path + second['batch_id']).json()['items']] == ['902', '903']
    with context() as db:
        state = db.get(models.PixivAccount, 1).sync_state
        assert state['recommendation_stream_discovery_1']['native_offset'] == 4
        assert state['recommendation_stream_personal_1']['native_offset'] == 2
        assert state['recommended_discovery_1']['batch'] != state['recommended_personal_1']['batch']


@pytest.mark.parametrize('mode', strategies.MODES)
def test_new_modes_accepted_private_batches_and_seen_validation(environment, mode):
    context, client, _ = environment
    response = client.post('/api/pixiv-ol/browse', json={'view':'recommendations', 'mode':mode, 'seen_pids':['900','901','900']})
    assert response.status_code == 202
    with context() as db:
        job = db.get(models.PixivJob, response.json()['id'])
        assert job.payload['seen_pids'] == ['900', '901']
        admin = jobs.enqueue(db, 2, 'browse_recommendations', job.payload)
        assert admin.id != job.id
        db.add(models.PixivRecommendationBatch(id='new', account_revision='rev', mode=mode,
                                               items=[service.normalize_artwork(artwork('950'))], profile={'actor_id':1,'vectors':{'secret':'weights'}}))
    data = client.get(f'/api/pixiv-ol/recommendations?mode={mode}').json()
    assert [row['pid'] for row in data['items']] == ['950']
    if mode == 'personal':
        assert data['profile'] == {}
    client.cookies.set('session_id', 'session-2')
    assert client.get(f'/api/pixiv-ol/recommendations?mode={mode}&batch_id=new').json()['items'] == []
    assert client.post('/api/pixiv-ol/browse', json={'view':'recommendations','mode':mode,'seen_pids':['not-a-PID']}).status_code == 422
