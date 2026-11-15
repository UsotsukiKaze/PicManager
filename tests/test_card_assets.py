import json
from pathlib import Path
from PIL import Image
from app import card_assets as assets


def test_tasks_deduplicate_and_keep_failed_retry_budget(tmp_path, monkeypatch):
    monkeypatch.setattr(assets.settings, 'DATA_PATH', str(tmp_path))
    assets.enqueue('avatar', '123', 'v1', {})
    assets.enqueue('avatar', '123', 'v1', {})
    with assets.connect() as db:
        assert db.execute('select count(*) from tasks').fetchone()[0] == 1
        db.execute("update tasks set status='failed',attempts=5")
    assets.enqueue('avatar', '123', 'v1', {})
    with assets.connect() as db:
        assert db.execute('select status,attempts from tasks').fetchone() == ('failed',5)
    assets.enqueue('avatar', '123', 'v2', {})
    with assets.connect() as db:
        assert db.execute('select count(*) from tasks').fetchone()[0] == 2


def test_resource_path_cannot_escape_and_avatar_version_changes(tmp_path, monkeypatch):
    monkeypatch.setattr(assets.settings, 'RESOURCE_PATH', str(tmp_path))
    p = tmp_path/'a.webp'
    Image.new('RGB',(32,32),'red').save(p)
    assert assets.local_resource('/resource/a.webp') == p
    assert assets.local_resource('/resource/../secret') is None
    assert assets.local_resource('https://other/secret') is None
    old=assets.file_version(p)
    Image.new('RGB',(64,64),'blue').save(p)
    assert assets.file_version(p) != old


def test_preview_does_not_reuse_undersized_image(tmp_path):
    source,target=tmp_path/'s.png',tmp_path/'p.webp'
    Image.new('RGB',(1800,2400),'red').save(source)
    Image.new('RGB',(300,400),'red').save(target)
    assert not assets.preview_ready(source,target,1800,2400)
    Image.new('RGB',(1200,1600),'red').save(target)
    assert assets.preview_ready(source,target,1800,2400)


def test_shared_cache_reuses_then_invalidates_for_avatar_and_theme(tmp_path, monkeypatch):
    from contextlib import contextmanager
    from types import SimpleNamespace
    from app import database, card_renderer
    from app.services import ImageService
    monkeypatch.setattr(assets.settings,'DATA_PATH',str(tmp_path))
    monkeypatch.setattr(assets.settings,'PREVIEW_PATH',str(tmp_path))
    monkeypatch.setattr(assets.settings,'AVATAR_PATH',str(tmp_path))
    source=tmp_path/'s.png';preview=tmp_path/'ABC.webp';avatar=tmp_path/'pixiv-123.webp'
    Image.new('RGB',(100,100),'red').save(source)
    Image.new('RGB',(100,100),'red').save(preview)
    Image.new('RGB',(32,32),'blue').save(avatar)
    row=SimpleNamespace(image_id='ABC',width=100,height=100)
    @contextmanager
    def context():
        yield SimpleNamespace(get=lambda *args:row)
    monkeypatch.setattr(database,'get_db_context',context)
    monkeypatch.setattr(ImageService,'image_full_path',lambda r:str(source))
    calls=[]
    monkeypatch.setattr(card_renderer,'render_card',lambda *args,**kwargs:calls.append(kwargs) or b'jpeg')
    info={'image_id':'ABC','artist':{'id':'123'},'characters':[]}
    assert assets.render(info,'light')==(b'jpeg',False)
    assert assets.render(info,'light')==(b'jpeg',True)
    Image.new('RGB',(64,64),'green').save(avatar)
    assert assets.render(info,'light')==(b'jpeg',False)
    assert assets.render(info,'dark')==(b'jpeg',False)
    assert len(calls)==3


def test_shared_cache_cannot_bypass_current_rating(monkeypatch):
    from contextlib import contextmanager
    from types import SimpleNamespace
    import pytest
    from fastapi import HTTPException
    from app.routers.integrations import bot_cards,bot_search
    from app.services import ImageService
    row=SimpleNamespace(age_rating='r18')
    query=SimpleNamespace(filter_by=lambda **kwargs:SimpleNamespace(first=lambda:row))
    @contextmanager
    def context():
        yield SimpleNamespace(query=lambda *args:query)
    monkeypatch.setattr(bot_cards,'get_db_context',context)
    monkeypatch.setattr(ImageService,'image_file_exists',lambda r:True)
    monkeypatch.setattr(bot_search,'_permitted',lambda *args:False)
    monkeypatch.setattr(assets,'render',lambda *args:pytest.fail('Unauthorized cache read'))
    for _ in range(2):
        with pytest.raises(HTTPException) as error:
            bot_cards.shared_card('ABC','group','42','light')
        assert error.value.status_code==403
