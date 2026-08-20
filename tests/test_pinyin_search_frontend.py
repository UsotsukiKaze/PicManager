from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SEARCH = (PROJECT_ROOT / "static" / "js" / "pinyin-search.js").read_text(encoding="utf-8")
AUTH = (PROJECT_ROOT / "static" / "js" / "auth.js").read_text(encoding="utf-8")
UI = (PROJECT_ROOT / "static" / "js" / "ui.js").read_text(encoding="utf-8")
TAG_SELECTOR = (PROJECT_ROOT / "static" / "js" / "tag-selector.js").read_text(encoding="utf-8")
CHARACTER_SELECTOR = (PROJECT_ROOT / "static" / "js" / "character-selector.js").read_text(encoding="utf-8")


def test_pinyin_engine_is_local_pinned_and_loaded_before_search_adapter():
    vendor = PROJECT_ROOT / "static" / "vendor" / "pinyin-pro-3.29.2.min.js"
    license_file = PROJECT_ROOT / "static" / "vendor" / "pinyin-pro-3.29.2.LICENSE.txt"
    assert vendor.is_file() and vendor.stat().st_size > 300_000
    assert license_file.is_file()
    assert AUTH.index("/static/vendor/pinyin-pro-3.29.2.min.js") < AUTH.index("/static/js/pinyin-search.js")


def test_search_adapter_supports_full_pinyin_initials_aliases_and_ranking():
    for contract in (
        "getFullPinyin(text)",
        "getPinyinInitials(text)",
        "for (const field of ['aliases', 'nicknames'])",
        "scoreRecord(record, query)",
        "right.score - left.score || left.index - right.index",
        "registerCustomPinyin(dictionary)",
    ):
        assert contract in SEARCH
    assert "binarySearchPinyin" not in SEARCH
    assert "pinyinBoundaries" not in SEARCH
    assert "engine.match" not in SEARCH
    assert (PROJECT_ROOT / "tests" / "pinyin_search_smoke.js").is_file()


def test_entity_search_callers_share_the_ranked_alias_and_nickname_filter():
    assert "return window.PinyinSearch.filter(items, query, 'name')" in TAG_SELECTOR
    assert "window.PinyinSearch.filter(this.availableCharacters, query, 'name')" in CHARACTER_SELECTOR
    assert "window.PinyinSearch.filter(this.allGroups, query, 'name')" in UI
    assert "window.PinyinSearch.filter(filtered, query, 'name')" in UI
    assert "window.PinyinSearch.filter(source, query, 'name')" in UI
    assert "nicknameMatched" not in CHARACTER_SELECTOR
