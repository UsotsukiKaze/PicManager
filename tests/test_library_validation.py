from datetime import datetime
from pathlib import Path
from sqlalchemy import create_engine,text
from sqlalchemy.orm import sessionmaker
from app import models,database
from app.config import settings


def test_mapping_and_check_migration_is_idempotent_and_preserves_existing_completion(tmp_path,monkeypatch):
    engine=create_engine(f"sqlite:///{tmp_path/'migration.db'}")
    models.Base.metadata.create_all(engine)
    Session=sessionmaker(bind=engine)
    with Session() as db:
        db.add(models.Group(id=1,name='游戏'))
        db.add(models.Image(image_id='0000000001',pid='100_p0',file_extension='png',file_path=str(tmp_path/'old.png')))
        db.flush()
        db.add(models.PixivImageMetadata(image_id='0000000001',work_id='100',page_index=0,page_count=1,tags=[],validated_at=datetime(2026,1,1)))
        db.commit()
    with engine.begin() as conn:
        conn.execute(text('DROP TABLE pixiv_tag_mappings'))
        conn.execute(text('CREATE TABLE pixiv_tag_mappings (id INTEGER PRIMARY KEY,normalized_tag VARCHAR(255) NOT NULL,group_context INTEGER NOT NULL DEFAULT 0,target_type VARCHAR(20) NOT NULL,target_id INTEGER,UNIQUE(normalized_tag,group_context))'))
        conn.execute(text("INSERT INTO pixiv_tag_mappings VALUES (1,'游戏',0,'group',1),(2,'坏链接',0,'character',999)"))
        conn.execute(text('DROP INDEX ix_images_local_checked_at'))
        conn.execute(text('ALTER TABLE images DROP COLUMN local_checked_at'))
    monkeypatch.setattr(database,'engine',engine)
    for attr in ('BASE_DIR','THUMB_PATH','PREVIEW_PATH'):monkeypatch.setattr(settings,attr,str(tmp_path))
    database.apply_migrations();database.apply_migrations()
    with Session() as db:
        image=db.get(models.Image,'0000000001');mapping=db.get(models.PixivTagMapping,1)
        assert image.pixiv_checked_at==datetime(2026,1,1)
        assert image.local_checked_at is None
        assert mapping.group_id==1 and mapping.original_tag=='游戏' and mapping.source=='manual'
        assert db.query(models.PixivTagMapping).count()==1
    engine.dispose()


def test_only_embedded_profile_allows_same_origin_frame():
    from starlette.responses import Response
    from main import _apply_security_headers
    normal, embedded = Response(), Response()
    _apply_security_headers(normal)
    _apply_security_headers(embedded, embedded_profile=True)
    assert normal.headers['x-frame-options']=='DENY'
    assert "frame-ancestors 'none'" in normal.headers['content-security-policy']
    assert embedded.headers['x-frame-options']=='SAMEORIGIN'
    assert "frame-ancestors 'self'" in embedded.headers['content-security-policy']
