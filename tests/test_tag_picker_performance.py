from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
TAG_SELECTOR = (PROJECT_ROOT / "static" / "js" / "tag-selector.js").read_text(encoding="utf-8")


def test_tag_picker_reuses_loaded_entities_instead_of_refetching_on_every_open():
    refresh = TAG_SELECTOR.split("async refreshData", 1)[1].split("option(item", 1)[0]
    assert "if (!forceRefresh && this.hasPickerData()) return" in refresh
    assert "ui.loadGroupsData(forceRefresh, true)" in refresh
    assert "ui.loadCharactersData(forceRefresh, true)" in refresh
    assert "ui.loadFeatureTagsData(forceRefresh, true)" in refresh
    assert "this.allowedTypes.map" in refresh


def test_tag_picker_debounces_search_and_group_changes_only_redraw_characters():
    assert "window.setTimeout(() => this.renderPicker(modalId, search.value), 90)" in TAG_SELECTOR
    assert "this.renderPicker(modalId, search.value, ['character'])" in TAG_SELECTOR
    assert "const shouldRender = type => !sections || sections.includes(type)" in TAG_SELECTOR
