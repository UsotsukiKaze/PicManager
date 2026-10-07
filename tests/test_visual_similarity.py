"""Offline accuracy, cache, permissions and state tests for lightweight hints."""
import json
from pathlib import Path

import pytest
from PIL import Image, ImageDraw

from test_pixiv_ol import environment as environment, artwork, install_fake
from app import models, pixiv_check, visual_similarity as visual
from app.config import settings
from app.integrations.pixiv_ol import service, provider


def drawing(seed=0):
    import random
    randomizer=random.Random(seed)
    image=Image.new('RGB',(480,640),'#b4ddeb');pen=ImageDraw.Draw(image)
    for index in range(60):
        x,y=randomizer.randrange(420),randomizer.randrange(590)
        pen.ellipse((x,y,x+randomizer.randrange(15,90),y+randomizer.randrange(15,90)),fill=tuple(randomizer.randrange(30,230) for _ in range(3)))
    pen.polygon([(240,170),(100,580),(410,560)],fill='#7d4e85')
    pen.ellipse((150,80,320,275),fill='#efd4bf')
    pen.line((100,330,400,480),fill='#253749',width=25)
    return image


def insert(db,path,image_id='0000000001',pid=None):
    image=models.Image(image_id=image_id,pid=pid,file_extension='png',file_path=str(path))
    db.add(image);db.flush();return image


def test_lightweight_hashes_detect_resize_and_screenshot_reject_unrelated_and_flat(environment):
    context,_,tmp=environment
    source=tmp/'original.png';drawing().save(source)
    resized=tmp/'resized.jpg';drawing().resize((180,240)).save(resized,quality=70)
    screenshot=Image.new('RGB',(760,940),'white');screenshot.paste(drawing().resize((360,480)),(180,250))
    ImageDraw.Draw(screenshot).rectangle((0,0,760,80),fill='#242732')
    screen=tmp/'screenshot.png';screenshot.save(screen)
    other=tmp/'different.png';drawing(99).save(other)
    flat=tmp/'flat.png';Image.new('RGB',(400,400),'white').save(flat)
    with context() as db:
        image=insert(db,source)
        result=visual.index_missing_batch(db)
        assert result=={'processed':1,'failed':0}
        assert visual.match_cached_preview(db,resized)[0]['image_id']==image.image_id
        assert visual.match_cached_preview(db,screen)[0]['image_id']==image.image_id
        assert visual.match_cached_preview(db,other)==[]
        assert visual.match_cached_preview(db,flat)==[]
        descriptor=image.visual_fingerprint.descriptor
        assert len(descriptor['variants'])<=6
        assert len(json.dumps(descriptor).encode())<4500
        assert visual.index_missing_batch(db)['processed']==0
        assert image.pixiv_checked_at is None and image.local_checked_at is None and image.pid is None


def test_fingerprint_batch_bounds_errors_and_file_or_pid_changes_invalidate(environment):
    context,_,tmp=environment
    source=tmp/'original.png';drawing().save(source)
    with context() as db:
        first=insert(db,source)
        second=insert(db,tmp/'missing.png','0000000002')
        insert(db,source,'0000000003','100')
        assert visual.index_missing_batch(db,limit=1)=={'processed':1,'failed':0}
        assert visual.index_missing_batch(db,limit=1)=={'processed':1,'failed':1}
        assert visual.index_missing_batch(db,limit=1)['processed']==0
        assert second.visual_fingerprint.descriptor['error']=='unreadable'
        first.perceptual_hash='a'*16;db.flush()
        assert first.visual_fingerprint is None
        assert visual.index_missing_batch(db)['processed']==1
        first.pid='1000';db.flush()
        assert first.visual_fingerprint is None
        assert visual.match_cached_preview(db,source)==[]
        assert db.query(models.ImageVisualFingerprint).count()==1
        db.delete(second);db.flush()
        assert db.query(models.ImageVisualFingerprint).count()==0


def test_pixiv_check_indexes_no_pid_without_account_or_remote_calls(environment,monkeypatch):
    context,_,tmp=environment
    monkeypatch.setattr(pixiv_check,'get_db_context',context)
    monkeypatch.setattr(service,'client_for_job',lambda *args:pytest.fail('fingerprinting must be offline'))
    path=tmp/'no_pid.png';drawing().save(path)
    with context() as db:
        insert(db,path);db.delete(db.get(models.PixivAccount,1))
    assert pixiv_check.scan_next(1)=={'status':'fingerprinted','processed':1,'failed':0}
    assert pixiv_check.scan_next(1)['status']=='complete'


def test_similarity_only_uses_cached_allowed_preview_and_is_private(environment,monkeypatch):
    context,client,tmp=environment
    source=tmp/'original.png';drawing().save(source)
    cache=Path(settings.DATA_PATH)/'pixiv_ol_previews'/'rev';cache.mkdir(parents=True)
    preview=cache/'100.webp';drawing().resize((180,240)).save(preview)
    with context() as db:
        insert(db,source);visual.index_missing_batch(db)
    service.save_artworks('rev',[artwork()], 'recommendations',1)
    monkeypatch.setattr(provider,'download',lambda *args,**kwargs:pytest.fail('comparison must not download'))
    response=client.get('/api/pixiv-ol/similarity',params={'pid':'100'})
    assert response.status_code==200 and response.json()['items'][0]['matches'][0]['image_id']=='0000000001'
    assert response.headers['Cache-Control']=='private, no-store'
    assert client.get('/api/pixiv-ol/similarity',params={'pid':'../100'}).status_code==422
    assert client.get('/api/pixiv-ol/similarity',params=[('pid','100')]*25).status_code==422
    preview.unlink()
    assert client.get('/api/pixiv-ol/similarity',params={'pid':'100'}).json()['items'][0]['matches']==[]
    with context() as db:
        row=db.query(models.PixivArtwork).first();row.metadata_json={**row.metadata_json,'x_restrict':1}
    assert client.get('/api/pixiv-ol/similarity',params={'pid':'100'}).json()['items']==[]
    client.cookies.set('session_id','session-3')
    assert client.get('/api/pixiv-ol/similarity',params={'pid':'100'}).status_code==403


def test_pid_lookup_caches_public_detail_without_adding_or_liking(environment,monkeypatch):
    context,client,_=environment;install_fake(monkeypatch)
    response=client.post('/api/pixiv-ol/lookup',json={'pid':'100'})
    assert response.status_code==200
    assert response.json()['pid']=='100' and response.json()['liked'] is False
    assert response.json()['preview_url'].startswith('/api/pixiv-ol/')
    assert 'originals' not in response.json() and 'preview' not in response.json()
    monkeypatch.setattr(service,'client_for_job',lambda *args:pytest.fail('lookup should reuse stored detail'))
    assert client.post('/api/pixiv-ol/lookup',json={'pid':'100'}).status_code==200
    with context() as db:
        assert db.query(models.PixivCartItem).count()==0 and db.query(models.PixivFeedback).count()==0
    assert client.post('/api/pixiv-ol/lookup',json={'pid':'https://example.com'}).status_code==422
    assert client.post('/api/pixiv-ol/lookup',json={'pid':'999'},headers={'Origin':'https://example.com'}).status_code==403
    client.headers.pop('X-Pixiv-OL')
    assert client.post('/api/pixiv-ol/lookup',json={'pid':'100'}).status_code==403
    client.headers['X-Pixiv-OL']='1';client.cookies.set('session_id','session-3')
    assert client.post('/api/pixiv-ol/lookup',json={'pid':'100'}).status_code==403


def test_pid_lookup_rejects_wrong_work_filtered_content_and_changed_account(environment,monkeypatch):
    context,client,_=environment;install_fake(monkeypatch)
    assert client.post('/api/pixiv-ol/lookup',json={'pid':'999'}).json()['detail']=='artwork_unavailable'
    class Filtered:
        def call(self,*args,**kwargs):return {'illust':{**artwork(),'x_restrict':1}}
        def close(self):pass
    monkeypatch.setattr(service,'client_for_job',lambda *args:Filtered())
    assert client.post('/api/pixiv-ol/lookup',json={'pid':'100'}).json()['detail']=='content_filtered'
    class Changed:
        def call(self,*args,**kwargs):
            with context() as db:db.get(models.PixivAccount,1).revision='other'
            return {'illust':artwork()}
        def close(self):pass
    monkeypatch.setattr(service,'client_for_job',lambda *args:Changed())
    assert client.post('/api/pixiv-ol/lookup',json={'pid':'100'}).json()['detail']=='account_changed'
    with context() as db:assert db.query(models.PixivArtwork).count()==0
