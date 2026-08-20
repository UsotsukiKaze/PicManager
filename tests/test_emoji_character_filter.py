from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app import models
from app.services import EmojiService


PROJECT_ROOT = Path(__file__).resolve().parents[1]
INDEX = (PROJECT_ROOT / "static" / "index.html").read_text(encoding="utf-8")
API = (PROJECT_ROOT / "static" / "js" / "api.js").read_text(encoding="utf-8")
EMOJI = (PROJECT_ROOT / "static" / "js" / "emoji-library.js").read_text(encoding="utf-8")
STYLE = (PROJECT_ROOT / "static" / "css" / "style.css").read_text(encoding="utf-8")


def test_available_character_facets_only_include_characters_with_available_emojis():
    engine = create_engine("sqlite:///:memory:")
    models.Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    try:
        group = models.Group(name="测试分组")
        popular = models.Character(name="角色甲", group=group)
        secondary = models.Character(name="角色乙", group=group)
        unused = models.Character(name="无表情角色", group=group)
        session.add_all([
            models.Emoji(emoji_id="EMOJI00001", file_extension="png", file_path="a.png", file_status="available", characters=[popular]),
            models.Emoji(emoji_id="EMOJI00002", file_extension="png", file_path="b.png", file_status="available", characters=[popular]),
            models.Emoji(emoji_id="EMOJI00003", file_extension="png", file_path="c.png", file_status="available", characters=[secondary]),
            models.Emoji(emoji_id="EMOJI00004", file_extension="png", file_path="d.png", file_status="missing", characters=[unused]),
        ])
        session.commit()

        facets = EmojiService.get_available_character_facets(session)

        assert [(item["name"], item["emoji_count"]) for item in facets] == [("角色甲", 2), ("角色乙", 1)]
    finally:
        session.close()
        engine.dispose()


def test_emoji_character_tabs_are_wired_to_immediate_filtering():
    assert 'id="emoji-character-tabs"' in INDEX
    assert 'aria-label="按角色筛选表情包"' in INDEX
    assert "async getEmojiCharacters()" in API
    assert "return this.request('/emojis/characters')" in API
    assert "renderCharacterTabs()" in EMOJI
    assert "selectCharacter(characterId)" in EMOJI
    assert "this.pagination.currentPage = 1" in EMOJI
    assert ".emoji-character-tabs" in STYLE
