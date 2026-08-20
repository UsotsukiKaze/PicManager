from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
JS_ROOT = PROJECT_ROOT / "static" / "js"


def _source(name: str) -> str:
    return (JS_ROOT / name).read_text(encoding="utf-8")


def test_ui_core_is_reduced_and_feature_methods_live_in_named_modules():
    core = _source("ui.js")
    assert len(core.splitlines()) < 2800
    assert "async loadImages(params = undefined)" not in core
    assert "\n    initializeSearchSelectors() {" not in core
    assert "\n    showModal(title, content" not in core
    assert "\n    isCacheValid(key" not in core

    assert "async loadImages(params = undefined)" in _source("image-list.js")
    assert "initializeSearchSelectors()" in _source("search-selector.js")
    assert "showModal(title, content" in _source("modal.js")
    assert "isCacheValid(key" in _source("entity-cache.js")


def test_entity_cache_deduplicates_inflight_requests_and_ignores_invalidated_responses():
    source = _source("entity-cache.js")
    assert "if (this.loadingStates[requestKey])" in source
    assert "this.loadingStates[requestKey] = request" in source
    assert "cacheGenerations" in source
    assert "=== generation" in source
    assert ".finally(() =>" in source


def test_ui_modules_are_loaded_before_core_and_installed_by_descriptors():
    auth = _source("auth.js")
    core = _source("ui.js")
    module_positions = [auth.index(f"/static/js/{name}") for name in (
        "entity-cache.js", "search-selector.js", "image-list.js", "modal.js"
    )]
    core_position = auth.index("/static/js/ui.js")

    assert module_positions == sorted(module_positions)
    assert all(position < core_position for position in module_positions)
    assert "Object.getOwnPropertyDescriptors(ModuleClass.prototype)" in core
    assert "Object.defineProperties(UIManager.prototype, descriptors)" in core
