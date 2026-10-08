"""Compound Pixiv tags keep every explicit target without spreading page roles."""
from datetime import datetime

import pytest
from test_pixiv_ol import environment as environment, artwork
from app import models
from app.tag_mappings import save_mapping, exact_mappings, CachedImageTagCheck
from app.integrations.pixiv_ol import service
from app.integrations.pixiv_ol.recommendations import TagIndex, build_profile
from app.integrations.pixiv_ol.cart_tags import refresh_draft, initial_state
from app.integrations.pixiv_ol.search_plan import build_search_plan
from test_pixiv_ol import FakeProvider, install_fake
from app.integrations.pixiv_ol import jobs


@pytest.fixture
def compound(environment):
    context, client, root = environment
    with context() as db:
        db.add_all([models.Character(id=10, name='妃咲', group_id=1),
                    models.Character(id=11, name='素世', group_id=1),
                    models.FeatureTag(id=2, name='泳装')])
    return context, client, root


def bind(client, tag, *targets):
    return client.post('/api/pixiv-ol/tag-mappings/batch', json={'bindings':[
        {'tag':tag, 'target_type':kind, 'target_id':id_} for kind, id_ in targets
    ]})


def test_costume_tag_keeps_role_and_feature_and_survives_reopening(compound):
    context, client, _ = compound
    assert bind(client, 'kisaki（水着）', ('character',10), ('feature',2)).status_code == 200
    assert bind(client, 'kisaki（水着）', ('character',10), ('feature',2)).status_code == 200
    with context() as db:
        assert db.query(models.PixivTagMapping).count() == 2
        match = TagIndex(db).match([{'name':'kisaki(水着)'}])
        assert match['character_ids'] == [10] and match['feature_tag_ids'] == [2]
        assert match['group_ids'] == [1] and not match['conflicts'] and not match['unmatched']
        assert len(match['evidence']) == 2
    rows = client.get('/api/pixiv-ol/tag-mappings').json()
    assert {row['target_type'] for row in rows} == {'character', 'feature'}


def test_pair_tag_matches_two_roles_and_searches_by_original_tag(compound):
    context, client, _ = compound
    assert bind(client, 'anosoyo', ('character',10), ('character',11)).status_code == 200
    with context() as db:
        index = TagIndex(db)
        match = index.match([{'name':'anosoyo'}])
        assert match['character_ids'] == [10,11] and len(match['evidence']) == 2
        assert not match['conflicts']
        preferences = {'groups':{'1':{'enabled':True}}}
        profile = build_profile(db,index,preferences)
        plan = build_search_plan(db,index,profile,preferences)
        assert any(row['word']=='anosoyo' and row['source']=='character_mapping' for row in plan)


def test_appending_another_role_does_not_replace_first(compound):
    context, client, _ = compound
    for id_ in (10,11):
        assert client.post('/api/pixiv-ol/tag-mappings',json={'tag':'anosoyo','target_type':'character','target_id':id_}).status_code == 200
    with context() as db:
        assert TagIndex(db).match([{'name':'anosoyo'}])['character_ids'] == [10,11]


def test_deleting_one_binding_leaves_the_other(compound):
    context, client, _ = compound
    bind(client,'anosoyo',('character',10),('character',11))
    first = client.get('/api/pixiv-ol/tag-mappings?target_type=character&target_id=10').json()[0]
    assert client.delete(f"/api/pixiv-ol/tag-mappings/{first['id']}").status_code == 200
    with context() as db:
        assert TagIndex(db).match([{'name':'anosoyo'}])['character_ids'] == [11]


def test_ignore_and_exact_match_do_not_accidentally_extend_manual_targets(compound):
    context, _, _ = compound
    with context() as db:
        save_mapping(db,'妃咲','character',10)
        save_mapping(db,'妃咲','character',11)
        assert exact_mappings(db,[{'name':'妃咲'}],{'groups':{'1':{'enabled':True}}}) == 0
        save_mapping(db,'妃咲','ignore',None,1)
        match = TagIndex(db).match([{'name':'妃咲'}],group_context=[1])
        assert not match['character_ids'] and match['evidence'][0]['type'] == 'ignore'
        assert db.query(models.PixivTagMapping).count() == 1
        save_mapping(db,'妃咲','character',10)
        assert TagIndex(db).match([{'name':'妃咲'}])['character_ids'] == [10]


def test_batch_invalid_target_rolls_back_all_bindings_and_requires_root(compound):
    context, client, _ = compound
    assert bind(client,'复合',('character',10),('feature',999)).status_code == 422
    with context() as db:
        assert db.query(models.PixivTagMapping).count() == 0
    client.cookies.set('session_id','session-2')
    assert bind(client,'复合',('character',10),('feature',2)).status_code == 403
    client.cookies.set('session_id','session-1')
    client.headers.pop('X-Pixiv-OL')
    assert bind(client,'复合',('character',10),('feature',2)).status_code == 403


def test_cart_refresh_expands_explicit_pair_but_keeps_confirmed_page_roles(compound):
    context, _, _ = compound
    with context() as db:
        save_mapping(db,'anosoyo','character',10)
        draft = {'group_ids':[1],'character_ids':[10],'feature_tag_ids':[]}
        draft['_tag_refresh'] = initial_state(draft)
        save_mapping(db,'anosoyo','character',11)
        index = TagIndex(db)
        art = {'tags':[{'name':'anosoyo'}],'page_count':1}
        assert refresh_draft(index,art,draft)['character_ids'] == [10,11]
        assert refresh_draft(index,art,draft,confirmed_page=True)['character_ids'] == [10]
        assert refresh_draft(index,{**art,'page_count':2},draft)['character_ids'] == [10]
        manual = {key:value for key,value in draft.items() if key != '_tag_refresh'}
        assert refresh_draft(index,art,manual)['character_ids'] == [10]


def test_empty_single_page_cart_gets_pair_but_separate_role_tags_are_ambiguous(compound):
    context, _, _ = compound
    with context() as db:
        save_mapping(db,'anosoyo','character',10)
        save_mapping(db,'anosoyo','character',11)
        draft = {'group_ids':[1],'character_ids':[],'feature_tag_ids':[]}
        draft['_tag_refresh'] = initial_state(draft)
        index = TagIndex(db)
        assert refresh_draft(index,{'tags':[{'name':'anosoyo'}],'page_count':1},draft)['character_ids'] == [10,11]
        assert refresh_draft(index,{'tags':[{'name':'妃咲'},{'name':'素世'}],'page_count':1},draft)['character_ids'] == []


def test_local_repair_keeps_manual_role_and_adds_costume(compound):
    context, _, root = compound
    with context() as db:
        save_mapping(db,'kisaki（水着）','character',10)
        save_mapping(db,'kisaki（水着）','feature',2)
        image = models.Image(image_id='0011223344',pid='100_p0',file_path=str(root/'image.png'),file_extension='png')
        image.groups = [db.get(models.Group,1)]
        image.characters = [db.get(models.Character,11)]
        image.pixiv_metadata = models.PixivImageMetadata(work_id='100',page_index=0,page_count=2,
            tags=[{'name':'kisaki（水着）'}],status='verified',validated_at=datetime.utcnow())
        db.add(image);db.flush()
        assert CachedImageTagCheck(db).check(image)['tag_links_added'] >= 1
        assert [row.id for row in image.characters] == [11]
        assert 2 in {row.id for row in image.feature_tags}


def test_cart_initial_match_includes_pair_without_series_tag(compound):
    context, client, _ = compound
    bind(client,'anosoyo',('character',10),('character',11))
    service.save_artworks('rev',[artwork(tags=[{'name':'anosoyo'}])],'recommended',1)
    response = client.post('/api/pixiv-ol/cart',json={'pid':'100'})
    assert response.status_code == 202
    assert response.json()['draft']['character_ids'] == [10,11]
    assert response.json()['draft']['group_ids'] == [1]


def test_compound_group_and_feature_both_survive_two_phase_matching(compound):
    context, _, _ = compound
    with context() as db:
        save_mapping(db,'复合分组','group',1)
        save_mapping(db,'复合分组','feature',2)
        match = TagIndex(db).match([{'name':'复合分组'}])
        assert match['group_ids'] == [1] and match['feature_tag_ids'] == [2]
        assert len(match['evidence']) == 2 and not match['unmatched']


def test_compound_pair_and_costume_import_together_offline(compound, monkeypatch):
    context, client, _ = compound
    install_fake(monkeypatch)
    raw = artwork(tags=[{'name':'anosoyo'}])
    class MatchingProvider(FakeProvider):
        def __init__(self, token):
            super().__init__(token)
            self.raw = raw
    monkeypatch.setattr(service,'Provider',MatchingProvider)
    assert bind(client,'anosoyo',('character',10),('character',11),('feature',2)).status_code == 200
    service.save_artworks('rev',[raw],'recommended',1)
    added = client.post('/api/pixiv-ol/cart',json={'pid':'100'}).json()
    assert jobs.Worker().run_once()
    assert client.put(f"/api/pixiv-ol/cart/{added['id']}",json={
        'pages':[0], 'group_ids':[1], 'character_ids':[10,11], 'feature_tag_ids':[2]
    }).status_code == 200
    monkeypatch.setattr(service,'client_for_job',lambda *_:pytest.fail('cached import must stay offline'))
    assert client.post('/api/pixiv-ol/cart/imports',json={'item_ids':[added['id']]}).status_code == 202
    assert jobs.Worker().run_once()
    with context() as db:
        image = db.query(models.Image).one()
        assert {row.id for row in image.characters} == {10,11}
        assert {row.name for row in image.feature_tags} == {'泳装','Pixiv'}


def test_deleting_role_keeps_companion_mapping(compound):
    context, client, _ = compound
    bind(client,'anosoyo',('character',10),('character',11))
    with context() as db:
        db.delete(db.get(models.Character,10))
    with context() as db:
        assert TagIndex(db).match([{'name':'anosoyo'}])['character_ids'] == [11]
