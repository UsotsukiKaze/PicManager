import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app import schemas
from app.config import settings
from app.routers.public_api import characters, emojis, feature_tags, groups, images
from app.services import (
    CharacterService,
    EmojiService,
    EmotionTagService,
    FeatureTagService,
    GroupService,
    ImageService,
)


@pytest.mark.parametrize("router,path", [
    (images.router, "/images/search"),
    (emojis.router, "/emojis/search"),
])
@pytest.mark.parametrize("query", [
    f"limit={settings.MAX_PAGE_SIZE + 1}",
    "limit=0",
    "offset=-1",
])
def test_search_route_rejects_unsafe_pagination(router, path, query):
    app = FastAPI()
    app.include_router(router)
    response = TestClient(app).get(f"{path}?{query}")
    assert response.status_code == 422


@pytest.mark.parametrize("router,path", [
    (groups.router, "/groups/"),
    (characters.router, "/characters/"),
    (feature_tags.router, "/feature-tags/"),
    (emojis.router, "/emotion-tags/"),
])
@pytest.mark.parametrize("query", [
    f"limit={settings.MAX_PAGE_SIZE + 1}",
    "limit=0",
    "skip=-1",
])
def test_list_route_rejects_unsafe_pagination(router, path, query):
    app = FastAPI()
    app.include_router(router)
    response = TestClient(app).get(f"{path}?{query}")
    assert response.status_code == 422


@pytest.mark.parametrize("params_type", [schemas.ImageSearchParams, schemas.EmojiSearchParams])
def test_search_schema_rejects_unsafe_pagination(params_type):
    with pytest.raises(ValidationError):
        params_type(limit=settings.MAX_PAGE_SIZE + 1)
    with pytest.raises(ValidationError):
        params_type(offset=-1)


class _TerminalQuery:
    def options(self, *args):
        return self

    def filter(self, *args):
        return self

    def join(self, *args):
        return self

    def distinct(self):
        return self

    def order_by(self, *args):
        return self

    def count(self):
        return 0

    def offset(self, value):
        self.offset_value = value
        return self

    def limit(self, value):
        self.limit_value = value
        return self

    def all(self):
        return []


class _FakeDb:
    def __init__(self):
        self.query_object = _TerminalQuery()

    def query(self, *args):
        return self.query_object


@pytest.mark.parametrize("service", [ImageService, EmojiService])
def test_service_layer_clamps_pagination_defensively(service):
    db = _FakeDb()
    unsafe = type("UnsafeParams", (), {
        "group_id": None,
        "character_id": None,
        "feature_tag_id": None,
        "emotion_id": None,
        "pid": None,
        "description": None,
        "age_rating": None,
        "offset": -20,
        "limit": settings.MAX_PAGE_SIZE * 10,
    })()

    if service is ImageService:
        service.search_images(db, unsafe)
    else:
        service.search_emojis(db, unsafe)

    assert db.query_object.offset_value == 0
    assert db.query_object.limit_value == settings.MAX_PAGE_SIZE


@pytest.mark.parametrize("service", [
    GroupService.get_groups,
    CharacterService.get_characters,
    FeatureTagService.get_feature_tags,
    EmotionTagService.get_emotion_tags,
])
def test_list_service_clamps_pagination_defensively(service):
    db = _FakeDb()

    if service is CharacterService.get_characters:
        service(db, group_id=None, skip=-20, limit=settings.MAX_PAGE_SIZE * 10)
    else:
        service(db, skip=-20, limit=settings.MAX_PAGE_SIZE * 10)

    assert db.query_object.offset_value == 0
    assert db.query_object.limit_value == settings.MAX_PAGE_SIZE
