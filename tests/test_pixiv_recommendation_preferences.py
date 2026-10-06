from datetime import datetime, timedelta

import pytest

from test_pixiv_ol import environment, artwork, FakeProvider
from app import models
from app.integrations.pixiv_ol import service
from app.integrations.pixiv_ol.recommendations import (
    TagIndex, build_profile, normalize, rank_candidates, recommendation_match,
)
from app.integrations.pixiv_ol.search_plan import build_search_plan


def mapping(db, word, kind, target, scope=0):
    db.add(models.PixivTagMapping(normalized_tag=normalize(word), original_tag=word,
                                  target_type=kind, target_id=target, group_context=scope))


def image(db, id_, pid, *, role=None, features=()):
    row = models.Image(image_id=id_, pid=pid, file_extension='png', file_path='fixture.png',
                       groups=[db.get(models.Group, 1)],
                       characters=[db.get(models.Character, role)] if role else [],
                       feature_tags=[db.get(models.FeatureTag, tag) for tag in features])
    db.add(row)
    return row


def like(db, pid, *, actor=1, revision='rev', value='like', days=0):
    db.add(models.PixivFeedback(account_revision=revision, actor_id=actor, pid=pid, value=value,
                                updated_at=datetime.utcnow() - timedelta(days=days)))


def cached(db, pid, tags):
    art = service.normalize_artwork(artwork(pid, [{'name':tag} for tag in tags]))
    # Equal dates and origin scores isolate the preference signal in ranking.
    db.add(models.PixivArtwork(account_revision='rev', pid=pid, author_id='9', title='fixture',
                               published_at=datetime(2026, 1, 1), metadata_json=art, origins=[]))
    return art


def profile_and_plan(db, rotation=0):
    db.flush()
    index = TagIndex(db)
    prefs = db.get(models.PixivAccount, 1).preferences
    profile = build_profile(db, index, prefs)
    return profile, build_search_plan(db, index, profile, prefs, rotation=rotation)


def test_search_uses_original_group_character_feature_and_unmapped_liked_tags(environment):
    context, _, _ = environment
    with context() as db:
        db.add(models.Character(id=10, name='本地角色', group_id=1))
        db.flush()
        mapping(db, 'GameNative', 'group', 1)
        mapping(db, 'RoleNative', 'character', 10, scope=1)
        mapping(db, 'WhiteNative', 'feature', 1)
        image(db, '0000000001', '100_p0', role=10, features=[1])
        cached(db, '200', ['GameNative', 'RoleNative', 'WhiteNative', 'Atmosphere'])
        like(db, '200')
        profile, plan = profile_and_plan(db)
        queries = {entry['word']:entry for entry in plan}
        assert {'GameNative', 'RoleNative', 'GameNative WhiteNative', 'GameNative Atmosphere'} <= queries.keys()
        assert all(queries[word]['search_target'] == 'exact_match_for_tags' for word in queries)
        assert profile['liked_raw_global'] == {'atmosphere':1}
        assert profile['characters'][1][10] > 0
        assert profile['tags'][1][1] > 0
        assert profile['related_seeds'][1][0] == '200'


def test_search_respects_scoped_override_ignored_tags_and_blocked_tags(environment):
    context, _, _ = environment
    with context() as db:
        db.add(models.Group(id=2, name='其他'))
        db.add(models.Character(id=10, name='角色', group_id=1))
        db.flush()
        mapping(db, 'OldGame', 'group', 1)
        mapping(db, 'OldGame', 'ignore', None, scope=1)
        mapping(db, 'BlockedGame', 'group', 1)
        mapping(db, 'Foreign', 'character', 10, scope=2)
        mapping(db, '白发', 'ignore', None)
        image(db, '0000000001', None, features=[1])
        db.get(models.PixivAccount, 1).preferences = {'groups':{'1':{'enabled':True}}, 'blocked_tags':['BlockedGame']}
        _, plan = profile_and_plan(db)
        assert [entry['word'] for entry in plan] == ['游戏']


@pytest.mark.parametrize('signal', ['feature', 'character', 'raw_like', 'ungrouped_feature_like'])
def test_each_preference_signal_promotes_matching_candidates(environment, signal):
    context, _, _ = environment
    with context() as db:
        db.add(models.Character(id=10, name='角色A', group_id=1))
        db.add(models.Character(id=11, name='角色B', group_id=1))
        db.flush()
        image(db, '0000000001', '100_p0', role=10 if signal == 'character' else None,
              features=[1] if signal == 'feature' else [])
        candidate_tags = ['游戏']
        if signal == 'feature':
            candidate_tags.append('白髪')
        elif signal == 'character':
            candidate_tags.append('角色A')
        else:
            cached(db, '300', ['白髪'] if signal == 'ungrouped_feature_like' else ['Atmosphere'])
            like(db, '300')
            candidate_tags.append('白髪' if signal == 'ungrouped_feature_like' else 'Atmosphere')
        cached(db, '200', candidate_tags)
        cached(db, '201', ['游戏', '角色B'] if signal == 'character' else ['游戏'])
    with context() as db:
        items, _ = rank_candidates(db, db.get(models.PixivAccount, 1))
        relevant = [item for item in items if item['pid'] in ('200', '201')]
        assert relevant[0]['pid'] == '200'
        assert relevant[0]['score'] > relevant[1]['score']
        assert any('匹配' in reason for reason in relevant[0]['reasons'])


def test_liked_library_work_learns_missing_mapped_features_without_changing_labels(environment):
    context, _, _ = environment
    with context() as db:
        row = image(db, '0000000001', '100_p0')
        cached(db, '100', ['游戏', '白髪'])
        like(db, '100')
        profile, plan = profile_and_plan(db)
        assert profile['tags'][1][1] > 0
        assert not row.feature_tags
        assert any(entry['word'] == '游戏 白髪' for entry in plan)


def test_plain_pid_pages_count_as_one_preference_sample(environment):
    context, _, _ = environment
    with context() as db:
        image(db, '0000000001', '100_p0', features=[1])
        image(db, '0000000002', '100_p1', features=[1])
        cached(db, '100', ['游戏', '白髪', 'Atmosphere'])
        like(db, '100')
        profile, _ = profile_and_plan(db)
        assert profile['samples'][1] == 2
        assert profile['tags'][1][1] == pytest.approx(0.6)
        assert profile['related_seeds'][1] == ['100']


def test_only_current_root_likes_affect_shared_preferences(environment):
    context, _, _ = environment
    with context() as db:
        for pid, tag, options in [
            ('100', 'Good', {}), ('101', 'Admin', {'actor':2}),
            ('102', 'OldAccount', {'revision':'old'}), ('103', 'Disliked', {'value':'dislike'}),
            ('104', 'Cancelled', {'value':'clear'}),
        ]:
            cached(db, pid, ['游戏', tag])
            like(db, pid, **options)
        profile, _ = profile_and_plan(db)
        assert profile['liked_raw_global'] == {'good':1}


@pytest.mark.parametrize('fallback', ['cart', 'metadata'])
def test_likes_use_cached_cart_or_verified_library_metadata_when_artwork_cache_is_gone(environment, fallback):
    context, _, _ = environment
    with context() as db:
        like(db, '100')
        if fallback == 'cart':
            db.add(models.PixivCartItem(id='cart', account_revision='rev', actor_id=1, pid='100', pages=[0],
                                        metadata_json=service.normalize_artwork(artwork('100', [{'name':'Atmosphere'}]))))
        else:
            row = image(db, '0000000001', '100_p0')
            row.pixiv_metadata = models.PixivImageMetadata(work_id='100', page_index=0, page_count=1,
                                                          tags=[{'name':'Atmosphere'}], status='verified')
        profile, _ = profile_and_plan(db)
        assert profile['liked_raw_global'] == {'atmosphere':1}


def test_scoped_character_can_identify_recommendation_group_but_ambiguous_scope_cannot(environment):
    context, _, _ = environment
    with context() as db:
        db.add(models.Group(id=2, name='其他'))
        db.add_all([models.Character(id=10, name='角色A', group_id=1),
                    models.Character(id=11, name='角色B', group_id=2)])
        db.flush()
        mapping(db, 'RoleNative', 'character', 10, scope=1)
        db.flush()
        tags = [{'name':'RoleNative'}]
        assert recommendation_match(TagIndex(db), tags, [1, 2])['character_ids'] == [10]
        mapping(db, 'RoleNative', 'character', 11, scope=2)
        db.flush()
        assert recommendation_match(TagIndex(db), tags, [1, 2])['group_ids'] == []


def test_search_cap_and_refresh_rotation_cover_all_signal_families(environment):
    context, _, _ = environment
    with context() as db:
        for g in range(1, 11):
            if g != 1:
                db.add(models.Group(id=g, name=f'分组{g}'))
            db.add(models.Character(id=100 + g, name=f'角色{g}', group_id=g))
        db.flush()
        for g in range(1, 11):
            mapping(db, f'Game{g}', 'group', g)
            mapping(db, f'Role{g}', 'character', 100 + g)
        db.flush()
        index = TagIndex(db)
        profile = {'quotas':{g:0.1 for g in range(1, 11)}, 'characters':{},
                   'tags':{g:{1:0.6} for g in range(1, 11)}, 'feature_query_tags':{1:['白髪']},
                   'liked_raw_global':{'atmosphere':1}, 'liked_raw_tags':{}, 'raw_tag_names':{'atmosphere':'Atmosphere'}}
        sources = set()
        for rotation in range(3):
            plan = build_search_plan(db, index, profile, {}, rotation=rotation)
            assert len(plan) == 20
            assert {entry['group'] for entry in plan[:10]} == set(range(1, 11))
            sources.update(entry['source'] for entry in plan)
        assert {'character_mapping', 'library_feature', 'liked_tag'} <= sources


def test_search_rotation_eventually_covers_lower_quota_groups_and_bound_characters(environment):
    context, _, _ = environment
    with context() as db:
        for g in range(2, 15):
            db.add(models.Group(id=g, name=f'分组{g}'))
        db.add_all([models.Character(id=10 + role, name=f'角色{role}', group_id=1) for role in range(4)])
        db.flush()
        for g in range(1, 15):
            mapping(db, f'Game{g}', 'group', g)
        for role in range(4):
            mapping(db, f'Role{role}', 'character', 10 + role)
        db.flush()
        profile = {'quotas':{g:1 / (g + 1) for g in range(1, 15)}, 'characters':{}, 'tags':{},
                   'feature_query_tags':{}, 'liked_raw_global':{}, 'liked_raw_tags':{}, 'raw_tag_names':{}}
        index, groups, roles = TagIndex(db), set(), set()
        for rotation in range(6):
            plan = build_search_plan(db, index, profile, {}, rotation=rotation)
            groups.update(entry['group'] for entry in plan)
            roles.update(entry['word'] for entry in plan if entry['source'] == 'character_mapping')
        assert groups == set(range(1, 15))
        assert roles == {'Role0', 'Role1', 'Role2', 'Role3'}


class RecordingProvider(FakeProvider):
    def __init__(self):
        self.calls = []

    def call(self, method, **kwargs):
        self.calls.append((method, kwargs))
        return {'illusts':[artwork('900')], 'next_url':None}


def test_progressive_refresh_defers_exact_search_and_remembers_target(environment):
    context, _, _ = environment
    with context() as db:
        mapping(db, 'GameNative', 'group', 1)
    remote = RecordingProvider()
    service.refresh_candidates(remote, 'rev', 1, progressive=True)
    assert [method for method, _ in remote.calls] == ['illust_recommended']
    with context() as db:
        plan = db.get(models.PixivAccount, 1).sync_state['recommendation_stream_combined']['deferred_queries']
        assert plan[0]['word'] == 'GameNative'
    service.refresh_candidates(remote, 'rev', 1, progressive=True, continuation=True)
    assert remote.calls[-1] == ('search_illust', {'word':'GameNative', 'search_target':'exact_match_for_tags'})


def test_legacy_deferred_search_still_resumes_and_changed_blocklist_skips_new_plan(environment):
    context, _, _ = environment
    with context() as db:
        db.get(models.PixivAccount, 1).sync_state = {'recommendation_stream_combined':{
            'exhausted':True, 'deferred_queries':[[1, '游戏']], 'deferred_seeds':[]}}
    remote = RecordingProvider()
    service.refresh_candidates(remote, 'rev', 1, progressive=True, continuation=True)
    assert remote.calls == [('search_illust', {'word':'游戏', 'search_target':'partial_match_for_tags'})]
    with context() as db:
        mapping(db, 'Native', 'group', 1)
    remote.calls.clear()
    service.refresh_candidates(remote, 'rev', 1, progressive=True)
    with context() as db:
        db.get(models.PixivAccount, 1).preferences = {'groups':{'1':{'enabled':True}}, 'blocked_tags':['Native']}
    result = service.refresh_candidates(remote, 'rev', 1, progressive=True, continuation=True)
    assert len(remote.calls) == 1 and not result['more']
