"""Modern shell deployment and compact list contracts, without touching live data."""
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path

from fastapi import FastAPI, Request, Response
from fastapi.testclient import TestClient
import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session

import main
from app import models, schemas
from app.services import ImageService
from app.routers.public_api import images


@pytest.fixture
def search_client(monkeypatch):
    now = datetime.utcnow()
    entity = dict(id=1, name="角色", nicknames=["别称"], group_id=2, group_name="分组", created_at=now, updated_at=now)
    record = dict(image_id="ABCD123456", file_path="unused.jpg", file_extension="jpg", pid="123_p0",
                  description="Full detail", age_rating="r12", width=800, height=1000,
                  created_at=now, updated_at=now, characters=[entity], groups=[],
                  pixiv_tags=[{"name": "标签"}], pixiv_verified=True, local_verified=True)

    @contextmanager
    def isolated_context():
        yield None

    monkeypatch.setattr(images, "get_db_context", isolated_context)
    monkeypatch.setattr(images.ImageService, "search_images", lambda db, params: ([record], 41))
    app = FastAPI()
    app.include_router(images.router)
    return TestClient(app)


def test_full_search_contract_remains_compatible(search_client):
    result = search_client.get('/images/search?limit=20&offset=20').json()
    assert result['images'][0]['description'] == 'Full detail'
    assert result['images'][0]['characters'][0]['nicknames'] == ['别称']
    assert result['images'][0]['pixiv_verified'] is True
    assert (result['total'], result['offset'], result['limit']) == (41, 20, 20)


def test_card_search_excludes_detail_only_metadata(search_client):
    response = search_client.get('/images/search?limit=20&offset=20&view=card')
    assert response.status_code == 200
    result = response.json()
    card = result['images'][0]
    assert card['pid'] == '123_p0'
    assert card['characters'][0]['group_name'] == '分组'
    assert not {'file_path', 'description', 'created_at', 'pixiv_tags', 'pixiv_verified'} & card.keys()
    assert 'nicknames' not in card['characters'][0]
    assert (result['total'], result['offset'], result['limit']) == (41, 20, 20)
    assert len(response.content) < len(search_client.get('/images/search?limit=20&offset=20').content)


def test_search_rejects_unknown_view(search_client):
    assert search_client.get('/images/search?view=wrong').status_code == 422


def test_card_query_keeps_artist_and_character_identity_without_per_image_tag_queries(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'cards.db'}")
    models.Base.metadata.create_all(engine)
    with Session(engine) as db:
        group = models.Group(name='分组')
        character = models.Character(name='角色', group=group)
        artist = models.PixivArtist(id='123', name='画师')
        db.add_all([group, character, artist])
        for index in range(20):
            image = models.Image(image_id=f'{index:010d}', file_path='unused.jpg', file_extension='jpg',
                                 age_rating='r12', pid=f'{1000 + index}_p0', characters=[character], groups=[group])
            image.pixiv_metadata = models.PixivImageMetadata(work_id=str(1000 + index), page_index=0, page_count=1,
                                                            artist=artist, tags=[{'name': '详细标签'}])
            db.add(image)
        db.commit()

    statements = []

    @event.listens_for(engine, 'before_cursor_execute')
    def count_selects(_conn, _cursor, statement, _params, _context, _many):
        if statement.lstrip().upper().startswith('SELECT'):
            statements.append(statement)

    try:
        with Session(engine) as db:
            cards, total = ImageService.search_images(db, schemas.ImageSearchParams(view='card', artist='123', limit=20))
            assert total == len(cards) == 20
            assert all(card['artist']['name'] == '画师' and card['characters'][0]['group_name'] == '分组' for card in cards)
            assert len(statements) == 2  # Count + page, independent of the 20 images.
            assert all('pixiv_image_metadata.tags' not in sql for sql in statements)
            assert all('nicknames' not in card['characters'][0] for card in cards)
    finally:
        engine.dispose()


@pytest.mark.asyncio
async def test_shell_prefers_build_but_falls_back_if_absent(monkeypatch, tmp_path):
    monkeypatch.setattr(main.settings, 'BASE_DIR', str(tmp_path))
    static = tmp_path / 'static'
    static.mkdir()
    (static / 'index.html').write_text('legacy', encoding='utf-8')
    assert Path((await main.root()).path) == static / 'index.html'
    (static / 'app').mkdir()
    (static / 'app/index.html').write_text('modern', encoding='utf-8')
    assert Path((await main.root()).path) == static / 'app/index.html'


@pytest.mark.parametrize('path,expected', [
    ('/static/app/assets/index-Ab1234_X.js', 'public, max-age=31536000, immutable'),
    ('/static/app/assets/index-Ab1234_X.css', 'public, max-age=31536000, immutable'),
    ('/static/app/index.html', 'no-cache'),
    ('/static/index.html', 'no-cache'),
    ('/static/app/assets/plain.js', 'public, max-age=14400'),
])
def test_build_cache_policy(path, expected):
    request = Request({'type': 'http', 'method': 'GET', 'path': path, 'query_string': b'', 'headers': []})
    response = Response()
    main._apply_production_cache_headers(request, response)
    assert response.headers['cache-control'] == expected


def test_build_is_packaged_and_api_404_not_replaced_with_spa():
    client = TestClient(main.app)
    headers = {'Host': 'localhost'}
    shell = client.get('/', headers=headers)
    assert shell.status_code == 200
    assert 'type="module"' in shell.text
    assert '/static/app/assets/' in shell.text
    assert client.get('/api/does-not-exist', headers=headers).status_code == 404
