from collections import Counter
from datetime import datetime, timedelta
from types import SimpleNamespace

import pytest

from test_pixiv_ol import environment, artwork, FakeProvider
from test_pixiv_recommendation_preferences import mapping, image, like, cached
from app import models
from app.integrations.pixiv_ol import service, strategies, jobs, provider
from app.integrations.pixiv_ol.recommendations import TagIndex, rank_candidates
from app.routers.integrations import pixiv_ol as pixiv_api


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


def test_stock_sparse_role_threshold_boosts_only_new_role_exploration(environment):
    context, _, _ = environment
    with context() as db:
        roles(db)
        db.add(models.Group(id=2, name='角色较多'))
        db.add_all(models.Character(id=100 + n, name=f'角色{n}', group_id=2) for n in range(21))
        db.get(models.PixivAccount, 1).preferences = {
            'groups':{'1':{'enabled':True}, '2':{'enabled':True}}}
        db.flush()
        profile = strategies.build_profile(db, TagIndex(db), db.get(models.PixivAccount, 1), 'stock')
        assert profile['character_counts'] == {1:2, 2:21}
        assert profile['sparse_character_groups'] == [1]
        assert profile['new_character_quotas'][1] > profile['quotas'][1]
        assert sum(profile['new_character_quotas'].values()) == pytest.approx(1)
        assert profile['new_character_fractions'][1] > profile['new_character_fractions'][2] == .15
        assert strategies.new_character_weights({1:.01, 2:.99}, {1:20, 2:21})[1] > .4
        assert strategies.new_character_weights({1:.01, 2:.99}, {1:21, 2:21}) == {1:.01, 2:.99}


def test_sparse_new_character_fraction_increases_to_eighty_percent():
    fractions = [strategies.new_character_fraction(count) for count in (21, 20, 10, 1, 0)]
    assert fractions == sorted(fractions)
    assert fractions[0] == .15
    assert fractions[-1] == .8
    assert fractions[1] > .15


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


@pytest.mark.parametrize('mode', ['personal', 'stock'])
def test_rank_prefers_recent_popular_work_within_same_interest_or_role(environment, mode):
    context, _, _ = environment
    with context() as db:
        roles(db)
    raws = []
    for pid, age, bookmarks in [('800', 180, 10000), ('801', 3, 120), ('802', 1, 1)]:
        raw = artwork(pid, [{'name':'GameNative'}, {'name':'RareNative'}, {'name':'WhiteNative'}])
        raw['user']['id'] = int(pid)
        raw['create_date'] = (datetime.utcnow() - timedelta(days=age)).isoformat() + 'Z'
        raw['total_bookmarks'] = bookmarks
        raws.append(raw)
    source = strategies.source_key('recommended', mode, 1)
    service.save_artworks('rev', raws, source, 1, ranks=True, source_batch='quality')
    with context() as db:
        account = db.get(models.PixivAccount, 1)
        account.sync_state = {source:{'batch':'quality'}}
        items, _ = strategies.rank(db, TagIndex(db), account, mode, 1)
        assert [item['pid'] for item in items] == ['801', '800', '802']


def test_personal_relevance_still_beats_unrelated_popularity(environment):
    context, _, _ = environment
    with context() as db:
        cached(db, '810', ['Atmosphere'])
        like(db, '810')
        cached(db, '811', ['Atmosphere'])
        cached(db, '812', ['Unrelated'])
        for pid, bookmarks in [('811', 1), ('812', 1000)]:
            art = db.query(models.PixivArtwork).filter_by(pid=pid).one()
            art.metadata_json = {**art.metadata_json, 'bookmarks':bookmarks,
                                 'published_at':datetime.utcnow().isoformat()}
        items, _ = strategies.rank(db, TagIndex(db), db.get(models.PixivAccount, 1), 'personal', 1)
        assert [item['pid'] for item in items].index('811') < [item['pid'] for item in items].index('812')


def test_missing_bookmark_count_keeps_previous_known_value(environment):
    context, _, _ = environment
    first = artwork('820')
    first['total_bookmarks'] = 42
    service.save_artworks('rev', [first], 'recommended_personal_1', 1)
    service.save_artworks('rev', [artwork('820')], 'search_personal_1', 1)
    with context() as db:
        assert db.query(models.PixivArtwork).filter_by(pid='820').one().metadata_json['bookmarks'] == 42


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


def test_sparse_groups_receive_more_new_character_slots_without_changing_known_quotas():
    items, profile, index = stock_fixture(known=400, unknown_role=0, unknown_group=0)
    for group in (1, 2):
        for n in range(40):
            pid = f'new-{group}-{n}'
            items.append({'pid':pid, 'author_id':pid, '_score':1, '_quality':1,
                          'match':{'group_ids':[group], 'character_ids':[], 'conflicts':[]}})
    profile['quotas'] = {1:.1, 2:.9}
    profile['sparse_character_groups'] = [1]
    profile['new_character_quotas'] = {1:.8, 2:.2}
    result = strategies.stock_schedule(items, profile, index)
    exploration = Counter(row['primary_group'] for row in result if row['stock_pool'] == 'new_character')
    assert exploration[1] >= 4 * exploration[2]
    assert sum(exploration.values()) == 27
    known = Counter(row['primary_group'] for row in result if row['stock_pool'] == 'known')
    assert known[1] < known[2] / 4


def test_sparse_group_gets_dynamic_slots_and_page_preserves_them():
    items, profile, index = stock_fixture(known=500, unknown_role=0, unknown_group=50)
    profile['quotas'] = {1:.5, 2:.5}
    profile['sparse_character_groups'] = [1]
    profile['new_character_fractions'] = {1:.8, 2:.15}
    for group in (1, 2):
        for n in range(120):
            pid = f'new-{group}-{n}'
            items.append({'pid':pid, 'author_id':pid, '_score':1, '_quality':1,
                          'match':{'group_ids':[group], 'character_ids':[], 'conflicts':[]}})
    result = strategies.stock_schedule(items, profile, index)
    counts = Counter(row['stock_pool'] for row in result)
    assert len(result) == 180
    assert 27 < counts['new_character'] <= 144
    assert counts['new_group'] == 9
    by_group = Counter(row['primary_group'] for row in result if row['stock_pool'] == 'new_character')
    assert by_group[1] > by_group[2]
    assert by_group[1] <= 72  # 180 * 50% group quota * 80% exploration
    assert profile['new_character_share'] == pytest.approx(.475)
    first_page = strategies.stock_page(list(enumerate(result)), 20, profile)
    assert Counter(row['stock_pool'] for _, row in first_page)['new_character'] > 3
    assert Counter(row['stock_pool'] for _, row in first_page)['new_character'] <= 16


def test_sparse_boost_requires_popular_supply_and_gap_uses_group_fraction():
    _, profile, _ = stock_fixture()
    profile['quotas'] = {1:.5, 2:.5}
    profile['new_character_fractions'] = {1:.8, 2:.15}
    assert strategies.stock_new_character_gap(1, Counter(), profile) == 72
    boosted, _, _, _ = strategies.stock_exploration_plan(profile, {1})
    cold, _, _, _ = strategies.stock_exploration_plan(profile, set())
    assert boosted == pytest.approx(.475)
    assert cold == pytest.approx(.15)


def test_all_sparse_groups_never_allocate_over_eighty_percent_new_roles():
    items, profile, index = stock_fixture(known=500, unknown_role=0, unknown_group=50)
    profile['quotas'] = {1:.5, 2:.5}
    profile['sparse_character_groups'] = [1, 2]
    profile['new_character_fractions'] = {1:.8, 2:.8}
    for group in (1, 2):
        for n in range(150):
            pid = f'new-{group}-{n}'
            items.append({'pid':pid, 'author_id':pid, '_score':1, '_quality':1,
                          'match':{'group_ids':[group], 'character_ids':[], 'conflicts':[]}})
    result = strategies.stock_schedule(items, profile, index)
    assert profile['new_character_share'] == pytest.approx(.8)
    assert len(result) == 180
    assert Counter(row['stock_pool'] for row in result)['new_character'] == 144
    assert Counter(row['stock_pool'] for _, row in strategies.stock_page(list(enumerate(result)), 20, profile))['new_character'] <= 16


def test_cold_sparse_candidates_do_not_receive_extra_exploration_slots():
    items, profile, index = stock_fixture(known=500, unknown_role=0, unknown_group=50)
    profile['quotas'] = {1:.5, 2:.5}
    profile['sparse_character_groups'] = [1]
    profile['new_character_fractions'] = {1:.8, 2:.15}
    for n in range(100):
        pid = f'cold-{n}'
        items.append({'pid':pid, 'author_id':pid, '_score':1, '_quality':.1,
                      'match':{'group_ids':[1], 'character_ids':[], 'conflicts':[]}})
    result = strategies.stock_schedule(items, profile, index)
    assert profile['new_character_share'] == pytest.approx(.15)
    assert Counter(row['stock_pool'] for row in result)['new_character'] <= 27


def test_sparse_bonus_does_not_promote_unpopular_new_character_supply():
    items, profile, index = stock_fixture(known=400, unknown_role=0, unknown_group=0)
    for group in (1, 2):
        for n in range(40):
            pid = f'new-{group}-{n}'
            items.append({'pid':pid, 'author_id':pid, '_score':1, '_quality':.1,
                          'match':{'group_ids':[group], 'character_ids':[], 'conflicts':[]}})
    profile['quotas'] = {1:.1, 2:.9}
    profile['sparse_character_groups'] = [1]
    profile['new_character_quotas'] = {1:.8, 2:.2}
    result = strategies.stock_schedule(items, profile, index)
    exploration = Counter(row['primary_group'] for row in result if row['stock_pool'] == 'new_character')
    assert exploration[1] <= 4
    assert exploration[2] >= 23


def test_sparse_group_picks_popular_new_role_before_feature_heavy_unpopular_one():
    items, profile, index = stock_fixture(known=400, unknown_role=0, unknown_group=0)
    profile['sparse_character_groups'] = [1]
    profile['new_character_quotas'] = {1:1, 2:0}
    for pid, quality, score in [('popular', .8, .6), ('unpopular', .1, .95)]:
        items.append({'pid':pid, 'author_id':pid, '_quality':quality, '_score':score,
                      'match':{'group_ids':[1], 'character_ids':[], 'conflicts':[]}})
    result = strategies.stock_schedule(items, profile, index)
    assert [row['pid'] for row in result if row['stock_pool'] == 'new_character'] == ['popular', 'unpopular']


def test_ambiguous_group_match_uses_sparse_group_for_new_role_exploration():
    _, profile, index = stock_fixture()
    profile['inventory'] = {1:500, 2:1}
    profile['sparse_character_groups'] = [1]
    profile['new_character_quotas'] = {1:.8, 2:.2}
    item = {'match':{'group_ids':[1, 2], 'character_ids':[], 'conflicts':[]}}
    assert strategies.stock_identity(item, profile, index) == ('new_character', 1, None)


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


def test_first_stock_visit_warms_bounded_shortage_queries_and_defers_remaining_searches(environment):
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
    assert [method for method, _ in remote.calls] == ['illust_recommended'] + ['search_illust'] * 3
    assert remote.calls[1][1]['word'] == 'GameNative'
    assert 'RareNative' in [params['word'] for _, params in remote.calls[1:]]
    assert result['more'] is True
    with context() as db:
        state = db.get(models.PixivAccount, 1).sync_state['recommendation_stream_stock_1']
        assert state['deferred_queries']
        assert 'RareNative' not in [row['word'] for row in state['deferred_queries']]


def test_missing_98_percent_weight_is_normalized_for_actual_supply():
    credits = Counter()
    result = [strategies._weighted_pick([1, 2], {0:.98, 1:.018, 2:.002}, credits) for _ in range(20)]
    assert Counter(result) == {1:18, 2:2}


def test_stock_group_and_role_shortages_preserve_weighted_order():
    items, profile, index = stock_fixture(known=900, unknown_role=0, unknown_group=0)
    profile['quotas'] = {0:.2, 1:.72, 2:.08}
    profile['character_quotas'][1] = {99:.2, 10:.08, 11:.72}
    result = strategies.stock_schedule(items, profile, index)
    assert Counter(item['primary_group'] for item in result[:20]) == {1:18, 2:2}
    roles_ = [item['primary_character'] for item in result if item['primary_group'] == 1]
    assert Counter(roles_[:20]) == {10:2, 11:18}


def test_stock_missing_cold_groups_cannot_donate_all_budget_to_native_hot_groups():
    items, profile, index = stock_fixture(known=900, unknown_role=100, unknown_group=100)
    profile['quotas'] = {0:.98, 1:.018, 2:.002}
    result = strategies.stock_schedule(items, profile, index)
    counts = Counter(item.get('primary_group') for item in result if item['stock_pool'] == 'known')
    assert counts[1] <= 4 and counts[2] <= 2
    assert profile['group_shortfalls'][0] > 100
    assert len(result) < 20


def test_recall_prioritizes_missing_groups_and_roles_over_generic_features():
    _, profile, index = stock_fixture()
    profile['quotas'] = {1:.5, 2:.4, 3:.1}
    profile['character_quotas'][3] = {30:1}
    candidates = [({'match':{'group_ids':[1], 'character_ids':[11], 'conflicts':[]}}, 0)] * 100
    queries = [
        {'group':None, 'source':'feature_exploration'},
        {'group':1, 'source':'character_mapping', 'character':11},
        {'group':2, 'source':'group_name'},
        {'group':2, 'source':'character_mapping', 'character':20},
        {'group':3, 'source':'character_mapping', 'character':30},
    ]
    selected = strategies.stock_recall_queries(queries, candidates, profile, index, limit=2)
    assert [(q['group'], q.get('character')) for q in selected] == [(2, 20), (3, 30)]


def test_recall_reserves_one_group_anchor_for_sparse_new_character_supply():
    _, profile, index = stock_fixture()
    profile['sparse_character_groups'] = [1]
    profile['new_character_quotas'] = {1:.8, 2:.2}
    candidates = [({'match':{'group_ids':[1], 'character_ids':[10], 'conflicts':[]}}, 0)] * 100
    queries = [
        {'group':1, 'word':'GameNative', 'source':'group_mapping'},
        {'group':1, 'word':'RareNative', 'character':11, 'source':'character_mapping'},
        {'group':None, 'word':'WhiteNative', 'source':'feature_exploration'},
    ]
    selected = strategies.stock_recall_queries(queries, candidates, profile, index, limit=2)
    assert [query['word'] for query in selected] == ['GameNative', 'RareNative']
    supplied = [({'match':{'group_ids':[1], 'character_ids':[], 'conflicts':[]},
                  'bookmarks':1000, 'published_at':datetime.utcnow().isoformat()}, 0)] * 25
    assert strategies.stock_recall_queries(queries, candidates + supplied, profile, index, limit=1)[0]['word'] == 'RareNative'


def test_sparse_group_anchor_continues_when_only_unpopular_new_roles_are_found(environment, monkeypatch):
    context, _, _ = environment
    with context() as db:
        roles(db)
    query = {'group':1, 'word':'GameNative', 'search_target':'exact_match_for_tags',
             'source':'group_mapping', 'terms':['GameNative']}
    monkeypatch.setattr(strategies, 'search_plan', lambda *args:[dict(query)])
    class Remote(FakeProvider):
        def call(self, method, **params):
            if method == 'illust_recommended':
                return {'illusts':[artwork(str(2000 + n),
                                         [{'name':'GameNative'}, {'name':'RareNative'}]) for n in range(144)],
                        'next_url':None}
            low = artwork('3000', [{'name':'GameNative'}])
            low['total_bookmarks'] = 0
            return {'illusts':[low], 'next_url':'https://app-api.pixiv.net/v1/search/illust?offset=30'}
    service.refresh_candidates(Remote('test'), 'rev', 1, 'stock', progressive=True)
    with context() as db:
        stream = db.get(models.PixivAccount, 1).sync_state['recommendation_stream_stock_1']
        assert len(stream['deferred_queries']) == 1
        assert stream['deferred_queries'][0]['cursor'] == {'offset':'30'}


def test_recall_still_searches_rare_roles_when_their_group_has_abundant_popular_supply():
    _, profile, index = stock_fixture()
    candidates = [({'match':{'group_ids':[1], 'character_ids':[10], 'conflicts':[]}}, 0)] * 200
    queries = [{'group':None, 'source':'feature_exploration'},
               {'group':1, 'character':10, 'source':'character_mapping'},
               {'group':1, 'character':11, 'source':'character_mapping'}]
    assert strategies.stock_recall_queries(queries, candidates, profile, index, limit=1)[0]['character'] == 11


def test_stock_plans_cover_all_enabled_groups_and_prefer_native_aliases(environment):
    context, _, _ = environment
    with context() as db:
        roles(db)
        for n in range(2, 22):
            db.add(models.Group(id=n, name=f'分组{n}'))
        db.flush()
        mapping(db, 'VOCALOID500users入り', 'group', 2)
        mapping(db, 'VOCALOID', 'group', 2)
        db.get(models.PixivAccount, 1).preferences = {'groups':{str(n):{'enabled':True} for n in range(1, 22)}}
        db.flush()
        account, index = db.get(models.PixivAccount, 1), TagIndex(db)
        profile = strategies.build_profile(db, index, account, 'stock')
        plan = strategies.search_plan(db, index, profile, account.preferences, 'stock', 0)
        assert {q['group'] for q in plan if q['group'] is not None} == set(range(1, 22))
        assert next(q['word'] for q in plan if q['group'] == 2) == 'VOCALOID'
        assert not any('500users入り' in q['word'] for q in plan)


def test_stock_queries_cover_more_than_two_rare_roles_and_rotate_the_tail(environment):
    context, _, _ = environment
    with context() as db:
        roles(db)
        for n in range(12, 18):
            db.add(models.Character(id=n, name=f'稀缺角色{n}', group_id=1))
            db.flush()
            mapping(db, f'RareMapped{n}', 'character', n, 1)
        db.flush()
        account, index = db.get(models.PixivAccount, 1), TagIndex(db)
        profile = strategies.build_profile(db, index, account, 'stock')
        first = strategies.search_plan(db, index, profile, account.preferences, 'stock', 0)
        next_ = strategies.search_plan(db, index, profile, account.preferences, 'stock', 1)
        selected = [q['character'] for q in first if q['source'] == 'character_mapping']
        rotated = [q['character'] for q in next_ if q['source'] == 'character_mapping']
        assert len(selected) == len(rotated) == 4
        assert selected[0] == rotated[0] == 12
        assert set(selected) != set(rotated)


def test_preferences_display_actual_stock_inverse_weights(environment):
    context, client, _ = environment
    with context() as db:
        roles(db)
        db.add(models.Group(id=2, name='空库存'))
        db.get(models.PixivAccount, 1).preferences = {'groups':{'1':{'enabled':True}, '2':{'enabled':True}}}
    quotas = client.get('/api/pixiv-ol/preferences').json()['quotas']
    assert sum(quotas.values()) == pytest.approx(1)
    assert quotas['2'] / quotas['1'] == pytest.approx(55)


@pytest.mark.parametrize('mode', ['personal', 'stock'])
def test_default_view_ignores_old_policy_but_explicit_reading_batch_remains_available(environment, mode):
    context, _, _ = environment
    with context() as db:
        db.add(models.PixivRecommendationBatch(id='old-policy', account_revision='rev', mode=mode,
            items=[service.normalize_artwork(artwork('800'))], profile={'actor_id':1, 'policy_version':'three-modes-v1'}))
    assert pixiv_api.recommendations(mode=mode, actor_id=1, offset=0, limit=20)['batch_id'] is None
    assert pixiv_api.recommendations(batch_id='old-policy', mode=mode, actor_id=1,
                                     offset=0, limit=20)['items'][0]['pid'] == '800'


def test_personal_continuation_restarts_old_policy_stream(environment):
    context, _, _ = environment
    with context() as db:
        account = db.get(models.PixivAccount, 1)
        account.sync_state = {'recommendation_stream_personal_1':{
            'policy_version':'three-modes-v2', 'source_batch':'old',
            'exhausted':True, 'deferred_queries':[], 'deferred_seeds':[]}}
    class Remote(FakeProvider):
        def __init__(self):
            self.calls = []
        def call(self, method, **params):
            self.calls.append(method)
            return {'illusts':[artwork('830')], 'next_url':None}
    remote = Remote()
    result = service.refresh_candidates(remote, 'rev', 1, 'personal', continuation=True, progressive=True)
    assert remote.calls == ['illust_recommended']
    assert result['count'] == 1
    with context() as db:
        stream = db.get(models.PixivAccount, 1).sync_state['recommendation_stream_personal_1']
        assert stream['policy_version'] == strategies.POLICY_VERSION
        assert stream['source_batch'] != 'old'


def test_stock_policy_upgrade_does_not_invalidate_personal_stream(environment):
    context, _, _ = environment
    with context() as db:
        db.get(models.PixivAccount, 1).sync_state = {'recommendation_stream_personal_1':{
            'policy_version':strategies.POLICY_VERSION, 'source_batch':'personal-current',
            'exhausted':True, 'deferred_queries':[], 'deferred_seeds':[]}}
    assert strategies.policy_version('stock') != strategies.policy_version('personal')
    assert service.refresh_candidates(None, 'rev', 1, 'personal', continuation=True, progressive=True) == {
        'count':0, 'more':False}


def test_background_waves_do_not_hide_pending_imports_from_the_job_list(environment):
    context, client, _ = environment
    with context() as db:
        importing = jobs.enqueue(db, 1, 'import', {'pid':'800', 'pages':[0]})
        importing.status = 'awaiting_duplicate'
        import_id = importing.id
        db.add_all([models.PixivJob(actor_id=1, account_revision='rev', kind='stock_refill', status='completed', payload={})
                    for _ in range(60)])
    visible = client.get('/api/pixiv-ol/jobs').json()
    assert [job['id'] for job in visible] == [import_id]
    assert visible[0]['status'] == 'awaiting_duplicate'


def install_stock_queue(environment, monkeypatch, size=36, failed=False):
    context, _, _ = environment
    with context() as db:
        roles(db)
        job = jobs.enqueue(db, 1, 'recommendations', {'mode':'stock', 'first_page':True})
        job_id = job.id
    plan = [{'group':1, 'character':11, 'word':f'RareNative{n}', 'search_target':'exact_match_for_tags',
             'source':'character_mapping', 'terms':['RareNative']} for n in range(size)]
    monkeypatch.setattr(strategies, 'search_plan', lambda *args:list(plan))
    class Remote(FakeProvider):
        def __init__(self):
            self.calls = []
        def call(self, method, **params):
            self.calls.append((method, params))
            if failed and method == 'search_illust':
                raise provider.PixivError('external_error')
            return {'illusts':[artwork(str(800 + len(self.calls)), [{'name':'GameNative'}, {'name':'RareNative'}])],
                    'next_url':None}
    remote = Remote()
    clients = []
    def client(*args):
        clients.append(args)
        return remote
    monkeypatch.setattr(service, 'client_for_job', client)
    return remote, clients, job_id


def test_stock_background_refill_drains_without_scrolling_and_preserves_reading_batch(environment, monkeypatch):
    from contextlib import contextmanager
    context, client, _ = environment
    remote, _, job_id = install_stock_queue(environment, monkeypatch)
    @contextmanager
    def production_context():
        with context() as db:
            db.autoflush = False
            yield db
    monkeypatch.setattr(service, 'get_db_context', production_context)
    monkeypatch.setattr(jobs, 'get_db_context', production_context)
    worker = jobs.Worker()
    assert worker.run_once()
    with context() as db:
        first = db.get(models.PixivJob, job_id).result['batch_id']
    original = client.get(f'/api/pixiv-ol/recommendations?mode=stock&batch_id={first}').json()
    for _ in range(20):
        if not worker.run_once():
            break
    else:
        pytest.fail('Background refill did not finish within its bounded plan')
    assert Counter(method for method, _ in remote.calls) == {'illust_recommended':1, 'search_illust':36}
    with context() as db:
        assert db.query(models.PixivRecommendationBatch).count() == 2
        assert not db.query(models.PixivJob).filter(models.PixivJob.status.in_(jobs.ACTIVE)).count()
        assert db.get(models.PixivAccount, 1).sync_state['recommendation_stream_stock_1']['deferred_queries'] == []
    assert client.get(f'/api/pixiv-ol/recommendations?mode=stock&batch_id={first}').json() == original


@pytest.mark.parametrize('invalidate', ['source_batch', 'started_at', 'policy_version'])
def test_foreground_jobs_overtake_refill_and_obsolete_refill_never_authenticates(environment, monkeypatch, invalidate):
    from datetime import datetime, timedelta
    context, _, _ = environment
    _, clients, _ = install_stock_queue(environment, monkeypatch)
    worker = jobs.Worker()
    assert worker.run_once()
    with context() as db:
        background_id = db.query(models.PixivJob).filter_by(kind='stock_refill').one().id
        foreground = jobs.enqueue(db, 1, 'browse_feed', {})
        foreground_id = foreground.id
    assert worker.run_once()
    with context() as db:
        assert db.get(models.PixivJob, foreground_id).status == 'completed'
        assert db.get(models.PixivJob, background_id).status == 'queued'
        account = db.get(models.PixivAccount, 1)
        stream = dict(account.sync_state['recommendation_stream_stock_1'])
        value = {'source_batch':'new-refresh', 'started_at':(datetime.utcnow() - timedelta(minutes=16)).isoformat(),
                 'policy_version':'three-modes-v1'}[invalidate]
        account.sync_state = {**account.sync_state, 'recommendation_stream_stock_1':{**stream, invalidate:value}}
    calls = len(clients)
    assert worker.run_once()
    assert len(clients) == calls
    with context() as db:
        assert db.get(models.PixivJob, background_id).status == 'completed'
        assert db.get(models.PixivJob, background_id).result['replenish'] is False


def test_stock_full_refresh_also_uses_bounded_foreground_and_background(environment, monkeypatch):
    context, _, _ = environment
    remote, _, job_id = install_stock_queue(environment, monkeypatch)
    with context() as db:
        db.get(models.PixivJob, job_id).payload = {'mode':'stock'}
    assert jobs.Worker().run_once()
    assert Counter(method for method, _ in remote.calls) == {'illust_recommended':1, 'search_illust':3}
    with context() as db:
        assert db.query(models.PixivJob).filter_by(kind='stock_refill', status='queued').count() == 1


def test_background_successor_keeps_seen_updates_received_during_fetch(environment, monkeypatch):
    context, _, _ = environment
    remote, _, _ = install_stock_queue(environment, monkeypatch, size=9)
    worker = jobs.Worker()
    assert worker.run_once()
    original, updated = remote.call, False
    def call(method, **params):
        nonlocal updated
        if not updated:
            with context() as db:
                running = db.query(models.PixivJob).filter_by(kind='stock_refill', status='running').one()
                jobs.enqueue(db, 1, 'stock_refill', {'mode':'stock', 'source_batch':running.payload['source_batch'],
                                                  'seen_pids':['802']})
            updated = True
        return original(method, **params)
    monkeypatch.setattr(remote, 'call', call)
    assert worker.run_once()
    with context() as db:
        successor = db.query(models.PixivJob).filter_by(kind='stock_refill', status='queued').one()
        assert successor.payload['seen_pids'] == ['802']


def test_unseen_warmed_supply_is_available_after_native_and_search_cursors_end(environment, monkeypatch):
    context, _, _ = environment
    _, _, job_id = install_stock_queue(environment, monkeypatch, size=6)
    original_profile = strategies.build_profile
    def profile(*args):
        return {**original_profile(*args), 'related_seeds':{}}
    monkeypatch.setattr(strategies, 'build_profile', profile)
    worker = jobs.Worker()
    assert worker.run_once()
    with context() as db:
        first = db.get(models.PixivJob, job_id).result['batch_id']
        seen = [item['pid'] for item in db.get(models.PixivRecommendationBatch, first).items]
    assert worker.run_once()
    result = service.refresh_candidates(None, 'rev', 1, 'stock', continuation=True, progressive=True, seen_pids=seen)
    assert result['count'] == 3
    with context() as db:
        fresh = [item['pid'] for item in db.get(models.PixivRecommendationBatch, result['batch_id']).items]
    assert not set(seen) & set(fresh)
    final = service.refresh_candidates(None, 'rev', 1, 'stock', continuation=True, progressive=True, seen_pids=seen + fresh)
    assert final['count'] == 0 and final['more'] is False


def test_warming_keeps_early_cold_supply_when_other_modes_fill_the_cache(environment):
    from datetime import datetime
    context, _, _ = environment
    with context() as db:
        roles(db)
    service.save_artworks('rev', [artwork('900', [{'name':'GameNative'}, {'name':'RareNative'}])],
                          'search_stock_1', 1, source_batch='current')
    with context() as db:
        account = db.get(models.PixivAccount, 1)
        account.sync_state = {'recommended_stock_1':{'batch':'current'}}
        metadata = service.normalize_artwork(artwork('901'))
        db.bulk_insert_mappings(models.PixivArtwork, [
            {'account_revision':'rev', 'pid':str(10000 + n), 'author_id':'9', 'title':'other mode',
             'published_at':datetime.utcnow(), 'metadata_json':{**metadata, 'pid':str(10000 + n)},
             'origins':[{'source':'recommended_personal_1', 'batch':'unrelated'}]}
            for n in range(1100)])
    with context() as db:
        items, _ = strategies.rank(db, TagIndex(db), db.get(models.PixivAccount, 1), 'stock', 1)
        assert [item['pid'] for item in items] == ['900']


def test_failed_stock_queries_are_bounded_and_do_not_stall_other_queries(environment, monkeypatch):
    context, _, _ = environment
    remote, _, _ = install_stock_queue(environment, monkeypatch, size=4, failed=True)
    worker = jobs.Worker()
    for _ in range(10):
        if not worker.run_once():
            break
    else:
        pytest.fail('Failed searches kept the refill queue alive indefinitely')
    assert sum(method == 'search_illust' for method, _ in remote.calls) == 12
    with context() as db:
        assert db.get(models.PixivAccount, 1).sync_state['recommendation_stream_stock_1']['deferred_queries'] == []


def test_stock_search_can_advance_when_first_page_contains_only_imported_work(environment, monkeypatch):
    context, _, _ = environment
    with context() as db:
        roles(db)
    query = {'group':1, 'character':11, 'word':'RareNative', 'search_target':'exact_match_for_tags',
             'source':'character_mapping', 'terms':['RareNative']}
    monkeypatch.setattr(strategies, 'search_plan', lambda *args:[dict(query)])
    class Remote(FakeProvider):
        def call(self, method, **params):
            if method == 'illust_recommended':
                return {'illusts':[], 'next_url':None}
            offset = int(params.get('offset', 0))
            return {'illusts':[artwork('1050' if not offset else '900', [{'name':'GameNative'}, {'name':'RareNative'}])],
                    'next_url':'https://app-api.pixiv.net/v1/search/illust?offset=30' if not offset else None}
    remote = Remote('test')
    first = service.refresh_candidates(remote, 'rev', 1, 'stock', progressive=True)
    assert first['count'] == 0
    second = service.refresh_candidates(remote, 'rev', 1, 'stock', continuation=True, progressive=True,
                                        replenish_batch=first['source_batch'])
    assert second['count'] == 1
    with context() as db:
        assert [item['pid'] for item in db.get(models.PixivRecommendationBatch, second['batch_id']).items] == ['900']


def test_parallel_api_calls_use_separate_sessions_and_isolate_errors(monkeypatch):
    import threading
    gate, lock = threading.Barrier(3), threading.Lock()
    instances, closed = [], []
    class API:
        def __init__(self, **kwargs):
            self.additional_headers = {}
            self.requests = SimpleNamespace(close=lambda:closed.append(self))
            with lock:
                instances.append(self)
        def set_auth(self, access, refresh):
            self.access, self.refresh = access, refresh
        def search_illust(self, word):
            gate.wait(timeout=5)
            return {'error':{'message':'rejected'}} if word == 'bad' else {'illusts':[word]}
    monkeypatch.setattr(provider, 'BoundedAPI', API)
    monkeypatch.setattr(provider, 'throttle', lambda:None)
    client = object.__new__(provider.Provider)
    client.api = SimpleNamespace(requests_kwargs={}, access_token='fake', refresh_token='fake', user_id=7, additional_headers={})
    results = client.call_many([('search_illust', {'word':word}) for word in ('first', 'bad', 'last')])
    assert results[0] == {'illusts':['first']}
    assert isinstance(results[1], provider.PixivError)
    assert results[2] == {'illusts':['last']}
    assert len(instances) == len(closed) == 3
    assert all(instance.access == 'fake' for instance in instances)


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
                                               items=[service.normalize_artwork(artwork('950'))],
                                               profile={'actor_id':1, 'policy_version':strategies.policy_version(mode),
                                                        'vectors':{'secret':'weights'}}))
    data = client.get(f'/api/pixiv-ol/recommendations?mode={mode}').json()
    assert [row['pid'] for row in data['items']] == ['950']
    if mode == 'personal':
        assert data['profile'] == {}
    client.cookies.set('session_id', 'session-2')
    assert client.get(f'/api/pixiv-ol/recommendations?mode={mode}&batch_id=new').json()['items'] == []
    assert client.post('/api/pixiv-ol/browse', json={'view':'recommendations','mode':mode,'seen_pids':['not-a-PID']}).status_code == 422
