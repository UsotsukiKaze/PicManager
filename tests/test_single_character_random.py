from contextlib import contextmanager

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app import models
from app.routers.integrations import bot
from app.services import ImageService


@pytest.fixture
def solo_db(monkeypatch):
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    models.Base.metadata.create_all(engine)
    with Session(engine) as db:
        group = models.Group(name="test")
        first = models.Character(name="first", group=group)
        second = models.Character(name="second", group=group)
        third = models.Character(name="only-mixed", group=group)
        db.add_all([group, first, second, third])
        db.flush()
        for image_id, characters, rating in (
            ("solo", [first], "r12"),
            ("solo-r18", [first], "r18"),
            ("mixed", [first, second, third], "r12"),
            ("untagged", [], "r12"),
        ):
            db.add(models.Image(image_id=image_id, file_extension="png", file_path=image_id,
                characters=characters, age_rating=rating, thumb_status=ImageService.THUMB_READY))
        db.commit()
        monkeypatch.setattr(ImageService, "image_file_exists", lambda image: True)
        ImageService._random_recent_image_ids.clear()
        yield db, first.id, third.id
    engine.dispose()


def test_random_only_selects_solo_and_keeps_rating_filter(solo_db):
    db, first_id, _ = solo_db
    for _ in range(4):
        image = ImageService.get_random_image(db, character_id=first_id,
            single_character=True, max_age_rating="r12")
        assert image["image_id"] == "solo"
        assert [role["id"] for role in image["characters"]] == [first_id]


def test_no_solo_returns_none_and_default_still_allows_mixed(solo_db):
    db, _, third_id = solo_db
    assert ImageService.get_random_image(db, character_id=third_id, single_character=True) is None
    assert ImageService.get_random_image(db, character_id=third_id)["image_id"] == "mixed"


def test_unscoped_solo_excludes_untagged_and_mixed(solo_db):
    db, _, _ = solo_db
    assert ImageService.get_random_image(db, single_character=True, max_age_rating="r12")["image_id"] == "solo"


def test_missing_solo_file_does_not_fall_back_to_mixed(solo_db, monkeypatch):
    db, first_id, _ = solo_db
    monkeypatch.setattr(ImageService, "image_file_exists", lambda image: image.image_id != "solo")
    assert ImageService.get_random_image(db, character_id=first_id,
        single_character=True, max_age_rating="r12") is None


def test_bot_endpoint_filters_and_returns_404_when_no_solo(solo_db, monkeypatch):
    db, first_id, third_id = solo_db

    @contextmanager
    def context():
        yield db

    monkeypatch.setattr(bot, "get_db_context", context)
    app = FastAPI()
    app.dependency_overrides[bot.require_bot_api_key] = lambda: None
    app.include_router(bot.router)
    client = TestClient(app)
    # Use the registered prefix so this also checks FastAPI query parsing.
    route = next(route for route in app.routes if route.name == "get_bot_random_image")
    response = client.get(route.path, params={"character_id": first_id, "single_character": "true"})
    assert response.status_code == 200
    assert response.json()["image_id"] == "solo"
    assert client.get(route.path, params={"character_id": third_id, "single_character": "true"}).status_code == 404
    assert client.get(route.path, params={"character_id": third_id}).status_code == 200
