from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import threading

import pytest
from PIL import Image, PngImagePlugin

from test_pixiv_ol import environment as environment, artwork
from app import models, temp_pixiv
from app.integrations.pixiv_ol import viewer, service
from app.routers.public_api import uploads


@pytest.fixture
def temp_environment(environment, monkeypatch):
    context, client, root = environment
    monkeypatch.setattr(temp_pixiv, 'get_db_context', context)
    monkeypatch.setattr(uploads, 'get_db_context', context)
    temp_pixiv.shutdown()
    temp_pixiv.RESULTS.clear()
    temp = Path(uploads.settings.TEMP_PATH)
    temp.mkdir(parents=True)
    calls = []

    class Remote:
        closed = False
        def call(self, method, **kwargs):
            calls.append(kwargs['illust_id'])
            return {'illust': artwork(kwargs['illust_id'], tags=[{'name':'游戏'}, {'name':'角色一'}, {'name':'角色二'}], pages=2)}
        def close(self):
            self.closed = True

    remote = Remote()
    monkeypatch.setattr(service, 'client_for_job', lambda *_args: remote)
    def preview(art, revision, page):
        path = root / f'preview-{art["pid"]}-{page}.png'
        Image.new('RGB', (80, 50), 'blue').save(path)
        return path, 'image/png'
    monkeypatch.setattr(viewer, 'clear_preview', preview)
    with context() as db:
        db.add_all([models.Character(id=1,name='角色一',group_id=1), models.Character(id=2,name='角色二',group_id=1)])
    yield context, client, temp, calls, remote
    temp_pixiv.shutdown()
    temp_pixiv.RESULTS.clear()


def create_file(temp, name='12345678_p1.png'):
    path = temp/name
    Image.new('RGB',(80,50),'blue').save(path, format='PNG')
    return path


def check_file(client, name='12345678_p1.png'):
    started = client.post('/api/upload/temp-pixiv/start')
    assert started.status_code == 200
    run = started.json()['run_id']
    result = client.post('/api/upload/temp-pixiv/check',json={'run_id':run,'filename':name})
    return run, result


@pytest.mark.parametrize('filename,expected',[
    ('12345678_p0.jpg',('12345678',0)),('12345678_p2_master1200.jpg',('12345678',2)),
    ('保存-12345678_p12.png',('12345678',12)),('12345678.png',('12345678',None)),
    ('https://www.pixiv.net/artworks/12345678',('12345678',None)),
    ('https://www.pixiv.net/en/artworks/12345678',('12345678',None)),
    ('holiday2026.png',None),('123_p0.png',None),('__drawn_by_artist__aabb.png',None),
])
def test_filename_hints_require_pixiv_identity(filename,expected):
    assert temp_pixiv.hint(filename) == expected


def test_embedded_source_url_without_filename_pid_is_recognized(temp_environment):
    _,client,temp,calls,_ = temp_environment
    metadata=PngImagePlugin.PngInfo()
    metadata.add_text('Source','https://www.pixiv.net/artworks/12345678')
    Image.new('RGB',(80,50),'blue').save(temp/'drawing.png',pnginfo=metadata)
    _,result=check_file(client,'drawing.png')
    assert result.status_code==200 and result.json()['status']=='review'
    assert result.json()['page'] is None and calls==['12345678']


def test_precheck_caches_identity_and_recalculates_tag_suggestions(temp_environment):
    context,client,temp,calls,remote=temp_environment
    create_file(temp)
    run,first=check_file(client)
    data=first.json()
    assert first.status_code==200 and data['status']=='verified' and data['pid']=='12345678_p1'
    assert data['artwork']['match']['character_ids']==[1,2]
    assert not any(key in data['artwork'] for key in ('originals','preview','author_avatar','page_previews'))
    client.post('/api/upload/temp-pixiv/stop',json={'run_id':run})
    assert remote.closed
    with context() as db:
        db.get(models.Character,2).name='different'
    _,again=check_file(client)
    assert again.json()['token']==data['token'] and calls==['12345678']
    assert again.json()['artwork']['match']['character_ids']==[1]
    with context() as db:
        assert db.query(models.Image).count()==0


def test_ordinary_file_does_not_call_pixiv(temp_environment):
    _,client,temp,calls,_=temp_environment
    create_file(temp,'holiday.png')
    _,result=check_file(client,'holiday.png')
    assert result.json()['status']=='ordinary' and not calls


def test_stop_during_lookup_prevents_late_cache_and_database_write(temp_environment,monkeypatch):
    context,client,temp,_,remote=temp_environment
    create_file(temp)
    entered,released=threading.Event(),threading.Event()
    def lookup(*args,**kwargs):
        entered.set()
        assert released.wait(5)
        return {'illust':artwork('12345678',pages=2)}
    monkeypatch.setattr(remote,'call',lookup)
    run=client.post('/api/upload/temp-pixiv/start').json()['run_id']
    with ThreadPoolExecutor(max_workers=1) as executor:
        future=executor.submit(temp_pixiv.check,run,'12345678_p1.png',1,uploads._duplicate_owner(type('Request',(),{'cookies':{'session_id':'session-1'}})()))
        assert entered.wait(3)
        assert client.post('/api/upload/temp-pixiv/stop',json={'run_id':run}).status_code==200
        released.set()
        with pytest.raises(temp_pixiv.PixivError,match='temp_precheck_stopped'):
            future.result(timeout=5)
    assert remote.closed and not temp_pixiv.RESULTS
    with context() as db:
        assert db.query(models.PixivArtwork).count()==0


def test_check_scope_permissions_and_traversal(temp_environment):
    _,client,temp,_,_=temp_environment
    create_file(temp)
    run=client.post('/api/upload/temp-pixiv/start').json()['run_id']
    client.cookies.set('session_id','session-2')
    assert client.post('/api/upload/temp-pixiv/check',json={'run_id':run,'filename':'12345678_p1.png'}).status_code==409
    client.cookies.set('session_id','session-1')
    assert client.post('/api/upload/temp-pixiv/check',json={'run_id':run,'filename':'../12345678_p1.png'}).status_code==409
    client.cookies.set('session_id','session-3')
    assert client.post('/api/upload/temp-pixiv/start').status_code==403
    assert client.get('/api/upload/temp-preview?filename=12345678_p1.png').status_code==403
    client.cookies.clear()
    assert client.post('/api/upload/temp-pixiv/start').status_code==401


def upload_data(result,name='12345678_p1.png'):
    return {'filename':name,'group_ids':[1],'character_ids':[1],'feature_tag_ids':[],
            'pid':'12345678_p1','pixiv_token':result.json()['token']}


def test_import_attaches_artist_raw_tags_and_validation_without_other_roles(temp_environment):
    context,client,temp,_,_=temp_environment
    create_file(temp)
    _,checked=check_file(client)
    response=client.post('/api/upload/temp',json=upload_data(checked))
    assert response.status_code==200, response.text
    with context() as db:
        image=db.get(models.Image,response.json()['image_id'])
        assert image.pid=='12345678_p1' and image.pixiv_checked_at
        assert image.pixiv_metadata.page_index==1 and image.pixiv_metadata.artist.name=='画师'
        assert [role.id for role in image.characters]==[1]
        assert len(image.pixiv_metadata.tags)==3
        assert 'Pixiv' in [tag.name for tag in image.feature_tags]
    assert not (temp/'12345678_p1.png').exists()


@pytest.mark.parametrize('change',['file','account','actor','page'])
def test_stale_or_foreign_proof_cannot_mark_image_validated(temp_environment,change):
    context,client,temp,_,_=temp_environment
    path=create_file(temp)
    _,checked=check_file(client)
    payload=upload_data(checked)
    if change=='file':
        Image.new('RGB',(81,50),'red').save(path)
    elif change=='account':
        with context() as db: db.get(models.PixivAccount,1).revision='changed'
    elif change=='actor':
        client.cookies.set('session_id','session-2')
    elif change=='page':
        payload['pid']='12345678_p7'
    result=client.post('/api/upload/temp',json=payload)
    assert result.status_code==409,result.text
    with context() as db: assert db.query(models.Image).count()==0
    assert path.exists()


def test_temp_preview_is_small_private_and_invalidates_when_source_changes(temp_environment):
    _,client,temp,_,_=temp_environment
    path=temp/'large.png'
    Image.new('RGB',(1800,1200),'blue').save(path)
    response=client.get('/api/upload/temp-preview',params={'filename':path.name})
    assert response.status_code==200 and response.headers['cache-control'].startswith('private')
    import io
    with Image.open(io.BytesIO(response.content)) as image:
        assert image.width==500 and image.height<500
    etag=response.headers['etag']
    assert client.get('/api/upload/temp-preview',params={'filename':path.name},headers={'If-None-Match':etag}).status_code==304
    Image.new('RGB',(1000,1000),'red').save(path)
    again=client.get('/api/upload/temp-preview',params={'filename':path.name},headers={'If-None-Match':etag})
    assert again.status_code==200 and again.headers['etag']!=etag


def test_changing_verified_page_requires_explicit_confirmation(temp_environment):
    context,client,temp,_,_=temp_environment
    create_file(temp)
    _,checked=check_file(client)
    payload=upload_data(checked)
    payload['pid']='12345678_p0'
    result=client.post('/api/upload/temp',json=payload)
    assert result.status_code==409 and result.json()['detail']=='temp_identity_unconfirmed'
    payload['identity_confirmed']=True
    result=client.post('/api/upload/temp',json=payload)
    assert result.status_code==200,result.text
    with context() as db:
        assert db.get(models.Image,result.json()['image_id']).pixiv_metadata.page_index==0


@pytest.mark.parametrize('keep',['distinct','merge-existing'])
def test_duplicate_confirmation_preserves_pixiv_metadata_and_page_specific_roles(temp_environment,keep):
    context,client,temp,_,_=temp_environment
    create_file(temp,'existing.png')
    stored=client.post('/api/upload/temp',json={'filename':'existing.png','group_ids':[1],'character_ids':[1],'pid':'12345678_p1'}).json()['image_id']
    create_file(temp)
    _,checked=check_file(client)
    duplicate=client.post('/api/upload/temp',json=upload_data(checked)).json()
    assert duplicate['status']=='duplicate'
    payload={'token':duplicate['duplicate_token'],'keep':keep,'metadata_sources':{'pid':'keep'}}
    if keep=='merge-existing':payload['keep']='merge-existing:'+stored
    result=client.post('/api/upload/duplicates/resolve',json=payload)
    assert result.status_code==200,result.text
    with context() as db:
        image=db.get(models.Image,result.json()['image_id'])
        assert image.pixiv_checked_at and image.pixiv_metadata.page_index==1
        assert [role.id for role in image.characters]==[1]
