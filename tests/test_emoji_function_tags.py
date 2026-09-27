from contextlib import contextmanager
from io import BytesIO
import json

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from PIL import Image
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app import models, schemas
from app.config import settings
from app.routers.integrations import bot
from app.routers.public_api import emojis
from app.services import EmojiService


@pytest.fixture
def emoji_api(tmp_path, monkeypatch):
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    models.Base.metadata.create_all(engine)
    sessions = sessionmaker(bind=engine)

    @contextmanager
    def database_context():
        with sessions() as db:
            try:
                yield db
                db.commit()
            except Exception:
                db.rollback()
                raise

    with database_context() as db:
        db.add_all([
            models.EmotionTag(id=1, name="love"),
            models.EmotionTag(id=2, name="angry"),
            models.EmotionTag(id=3, name="#睡觉"),
            models.EmotionTag(id=4, name="#摸头"),
        ])

    monkeypatch.setattr(emojis, "get_db_context", database_context)
    monkeypatch.setattr(bot, "get_db_context", database_context)
    monkeypatch.setattr(emojis, "require_admin_user_id", lambda request: 1)
    monkeypatch.setattr(settings, "BASE_DIR", str(tmp_path))
    monkeypatch.setattr(settings, "TEMP_PATH", str(tmp_path / "temp"))
    monkeypatch.setattr(settings, "EMOJI_PATH", str(tmp_path / "resource" / "emojis"))
    EmojiService._random_recent_emoji_ids.clear()
    app = FastAPI()
    app.include_router(emojis.router)
    app.include_router(bot.router, prefix="/bot")
    app.dependency_overrides[bot.require_bot_api_key] = lambda: None
    with TestClient(app) as client:
        yield client, sessions, tmp_path
    EmojiService._random_recent_emoji_ids.clear()
    engine.dispose()


def upload(client, ids, endpoint="/emojis/upload"):
    output = BytesIO()
    Image.new("RGB", (8, 8), "red").save(
        output, format="GIF", save_all=True,
        append_images=[Image.new("RGB", (8, 8), "blue")], duration=100, loop=0,
    )
    return client.post(endpoint, data={"emotion_ids": json.dumps(ids)}, files={
        "file": ("emoji.gif", output.getvalue(), "image/gif"),
    })


@pytest.mark.parametrize("endpoint", ["/emojis/upload", "/bot/emojis/upload"])
@pytest.mark.parametrize("ids", [[], [1], [3], [4, 1]])
def test_upload_and_read_preserve_optional_emotion_and_function(emoji_api, endpoint, ids):
    client, _, _ = emoji_api
    response = upload(client, ids, endpoint)
    assert response.status_code == 200, response.text
    result = response.json()
    emoji_id = result.get("emoji_id") or result["image_id"]
    detail = client.get(f"/emojis/{emoji_id}")
    assert detail.status_code == 200, detail.text
    tags = detail.json()["emotions"]
    assert [tag["id"] for tag in tags] == sorted(ids)
    assert [tag["tag_type"] for tag in tags] == ["emotion" if i < 3 else "function" for i in sorted(ids)]


@pytest.mark.parametrize("ids", [[1, 2], [3, 4], [1, 2, 3], [1, 999]])
@pytest.mark.parametrize("endpoint", ["/emojis/upload", "/bot/emojis/upload"])
def test_invalid_tag_selection_is_rejected_without_storing_file(emoji_api, ids, endpoint):
    client, sessions, tmp_path = emoji_api
    response = upload(client, ids, endpoint)
    assert response.status_code == 400, response.text
    with sessions() as db:
        assert db.query(models.Emoji).count() == 0
    assert not list(tmp_path.glob("resource/emojis/*"))


def test_update_preserves_both_tags_and_can_remove_each_independently(emoji_api):
    client, _, _ = emoji_api
    emoji_id = upload(client, [1, 4]).json()["image_id"]
    url = f"/emojis/{emoji_id}"
    for payload, expected in [
        ({"description": "updated"}, [1, 4]),
        ({"group_ids": [], "character_ids": []}, [1, 4]),
        ({"emotion_ids": [4]}, [4]),
        ({"emotion_ids": [2, 3]}, [2, 3]),
        ({"emotion_ids": [2]}, [2]),
        ({"emotion_ids": []}, []),
        ({"emotion_ids": [1, 4, 1]}, [1, 4]),
    ]:
        assert client.put(url, json=payload).status_code == 200
        assert [tag["id"] for tag in client.get(url).json()["emotions"]] == expected

    rejected = client.put(url, json={"emotion_ids": [3, 4], "description": "must not persist"})
    assert rejected.status_code == 400
    detail = client.get(url).json()
    assert detail["description"] == "updated"
    assert [tag["id"] for tag in detail["emotions"]] == [1, 4]


def test_service_validates_before_file_copy(emoji_api):
    _, sessions, tmp_path = emoji_api
    with sessions() as db, pytest.raises(ValueError, match="基础情绪"):
        EmojiService.create_emoji(db, schemas.EmojiCreate(emotion_ids=[1, 2]), "not-a-file.gif", "bad.gif")
    assert not list(tmp_path.glob("resource/emojis/*"))


def test_search_and_random_support_function_only_and_combination(emoji_api):
    client, _, _ = emoji_api
    sleep = upload(client, [3]).json()["image_id"]
    love_pat = upload(client, [1, 4]).json()["image_id"]
    angry_pat = upload(client, [2, 4]).json()["image_id"]
    pure_pat = upload(client, [4]).json()["image_id"]
    love = upload(client, [1]).json()["image_id"]
    cases = [
        ({"function_id": 3}, {sleep}),
        ({"function_id": 4}, {love_pat, angry_pat, pure_pat}),
        ({"emotion_id": 1}, {love_pat, love}),
        ({"emotion_id": 1, "function_id": 4}, {love_pat}),
        ({"emotion_id": 4}, {love_pat, angry_pat, pure_pat}),
        ({"emotion_id": 1, "function_id": 3}, set()),
        ({"function_id": 1}, set()),
    ]
    for params, expected in cases:
        response = client.get("/emojis/search", params=params)
        assert response.status_code == 200, response.text
        result = response.json()
        assert result["total"] == len(expected)
        assert {item["emoji_id"] for item in result["emojis"]} == expected
        for endpoint in ("/emojis/random", "/bot/emojis/random"):
            response = client.get(endpoint, params=params)
            assert response.status_code == (200 if expected else 404), response.text
            if expected:
                assert response.json()["emoji_id"] in expected


def test_catalog_classification_and_rename_cannot_break_cardinality(emoji_api):
    client, _, _ = emoji_api
    emoji_id = upload(client, [1, 4]).json()["image_id"]
    for endpoint in ("/emotion-tags/", "/bot/emotion-tags"):
        tags = client.get(endpoint).json()
        assert {tag["id"]: tag["tag_type"] for tag in tags} == {
            1: "emotion", 2: "emotion", 3: "function", 4: "function",
        }
    for tag_id, name in ((1, "#喜爱"), (4, "摸头")):
        response = client.put(f"/emotion-tags/{tag_id}", json={"name": name, "aliases": ["changed"]})
        assert response.status_code == 400, response.text
    detail = client.get(f"/emojis/{emoji_id}").json()
    assert [tag["name"] for tag in detail["emotions"]] == ["love", "#摸头"]
    assert all(not tag["aliases"] for tag in detail["emotions"])

    # A lone tag may change category safely, and aliases do not determine its type.
    sleep = upload(client, [3]).json()["image_id"]
    response = client.put("/emotion-tags/3", json={"name": " sleepy ", "aliases": ["#睡觉"]})
    assert response.status_code == 200, response.text
    assert response.json()["name"] == "sleepy"
    assert response.json()["tag_type"] == "emotion"
    assert client.get(f"/emojis/{sleep}").json()["emotions"][0]["tag_type"] == "emotion"


@pytest.mark.parametrize("name", ["", "  ", "#", "#  "])
def test_tag_creation_rejects_empty_names(emoji_api, name):
    client, _, _ = emoji_api
    assert client.post("/emotion-tags/", json={"name": name}).status_code == 422
    assert client.put("/emotion-tags/1", json={"name": name}).status_code == 422


def test_new_function_tag_is_inferred_from_name(emoji_api):
    client, _, _ = emoji_api
    response = client.post("/emotion-tags/", json={"name": "  #打招呼  ", "aliases": ["hello"]})
    assert response.status_code == 200, response.text
    assert response.json()["name"] == "#打招呼"
    assert response.json()["tag_type"] == "function"
