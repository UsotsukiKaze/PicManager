from app.routers.integrations import bot


def test_bot_image_url_uses_signed_original_not_store_path(monkeypatch):
    monkeypatch.setattr(bot.settings, "PUBLIC_BASE_URL", "https://pic.example/")

    result = bot._with_image_url({
        "image_id": "ABCDEF1234",
        "file_path": "resource/store/private-original.png",
        "age_rating": "r18",
    })

    expected_thumbnail = "https://pic.example/resource/thumbs/ABCDEF1234.webp"
    assert result["image_url"].startswith("https://pic.example/resource/originals/ABCDEF1234?")
    assert result["thumbnail_url"] == expected_thumbnail
    assert result["original_image_url"] == result["image_url"]
    assert "expires=" in result["image_url"]
    assert "signature=" in result["image_url"]
    assert "resource/store" not in result["image_url"]
    assert "resource/store" not in result["original_image_url"]
    assert "file_path" not in result
    assert "private-original.png" not in repr(result)


def test_bot_image_urls_are_empty_without_managed_image_id(monkeypatch):
    monkeypatch.setattr(bot.settings, "PUBLIC_BASE_URL", "")

    result = bot._with_image_url({"file_path": "resource/store/private-original.png"})

    assert result["image_url"] is None
    assert result["thumbnail_url"] is None
    assert result["original_image_url"] is None


def test_bot_character_list_aggregates_service_pages(monkeypatch):
    characters = [{"id": index, "name": f"character-{index}"} for index in range(250)]

    class FakeDbContext:
        def __enter__(self):
            return object()

        def __exit__(self, *args):
            return None

    monkeypatch.setattr(bot.settings, "MAX_PAGE_SIZE", 100)
    monkeypatch.setattr(bot, "get_db_context", lambda: FakeDbContext())
    monkeypatch.setattr(
        bot.CharacterService,
        "get_characters",
        lambda db, group_id=None, skip=0, limit=100: characters[skip:skip + limit],
    )

    result = bot.get_bot_characters(limit=5000)

    assert result == characters
