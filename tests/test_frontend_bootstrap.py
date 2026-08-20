import re
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
INDEX_HTML = PROJECT_ROOT / "static" / "index.html"
AUTH_JS = PROJECT_ROOT / "static" / "js" / "auth.js"
MAIN_JS = PROJECT_ROOT / "static" / "js" / "main.js"
UI_JS = PROJECT_ROOT / "static" / "js" / "ui.js"
UI_MODULES = [
    PROJECT_ROOT / "static" / "js" / name
    for name in ("entity-cache.js", "search-selector.js", "image-list.js", "modal.js")
]


def _ui_source() -> str:
    return "\n".join(path.read_text(encoding="utf-8") for path in [*UI_MODULES, UI_JS])
SECURITY_JS = PROJECT_ROOT / "static" / "js" / "security.js"
CHARACTER_SELECTOR_JS = PROJECT_ROOT / "static" / "js" / "character-selector.js"
TAG_SELECTOR_JS = PROJECT_ROOT / "static" / "js" / "tag-selector.js"
UPLOAD_JS = PROJECT_ROOT / "static" / "js" / "upload.js"


def test_anonymous_shell_only_eagerly_loads_auth_bootstrap():
    html = INDEX_HTML.read_text(encoding="utf-8")
    eager_scripts = re.findall(r'<script\b[^>]*\bsrc="([^"]+)"', html)

    assert eager_scripts == ["/static/js/auth.js?v=20260820o"]
    assert 'class="app-booting"' in html
    assert '<noscript><meta http-equiv="refresh" content="0; url=/login"></noscript>' in html
    assert 'rel="stylesheet" href="/static/css/style.css' not in html
    assert 'rel="stylesheet" href="/static/css/icons.css' not in html
    eager_images = re.findall(r'<img\b(?=[^>]*?(?<![\w-])src=")([^>]*)>', html)
    assert eager_images == []
    assert 'src=""' not in html


def test_authenticated_bootstrap_loads_application_only_after_auth_success():
    source = AUTH_JS.read_text(encoding="utf-8")

    auth_check = source.index("const authSuccess = await this.checkAuth()")
    auth_guard = source.index("if (!authSuccess)", auth_check)
    application_load = source.index("await this.loadApplication()", auth_guard)
    assert auth_check < auth_guard < application_load

    for asset in (
        "/static/css/style.css?v=20260820o",
        "/static/js/security.js?v=20260820a",
        "/static/js/character-selector.js?v=20260820a",
        "/static/js/tag-selector.js?v=20260820d",
        "/static/js/api.js?v=20260820h",
        "/static/js/entity-cache.js?v=20260820a",
        "/static/js/search-selector.js?v=20260820d",
        "/static/js/image-list.js?v=20260820b",
        "/static/js/modal.js?v=20260820a",
        "/static/js/ui.js?v=20260820d",
        "/static/js/main.js?v=20260812c",
    ):
        assert asset in source

    assert "document.documentElement.classList.remove('app-booting')" in source
    assert "await this.waitForDocumentBody()" in source
    assert "const scriptsReady = Promise.all(scripts.map(src => this.loadScript(src)))" in source
    assert "await scriptsReady" in source
    assert "for (const src of scripts)" not in source
    assert "script.async = false" in source


def test_user_controlled_entity_names_are_html_escaped_before_rendering():
    security_source = SECURITY_JS.read_text(encoding="utf-8")
    ui_source = _ui_source()
    character_source = CHARACTER_SELECTOR_JS.read_text(encoding="utf-8")
    tag_source = TAG_SELECTOR_JS.read_text(encoding="utf-8")

    assert "function escapeHTML(value)" in security_source
    assert "replace(/[&<>\"']/g" in security_source
    assert "window.PicManagerSecurity.escapeHTML(value)" in ui_source
    assert "this.escapeHTML(char.name)" in character_source
    assert "this.escapeHTML(item.name)" in tag_source


def test_all_management_entity_fields_are_escaped_at_html_render_sinks():
    ui_source = _ui_source()

    for expression in (
        "this.escapeHomeRankingText(group.name)",
        "this.escapeHomeRankingText(group.description || '无描述')",
        "this.escapeHomeRankingText(character.name)",
        "this.escapeHomeRankingText(tag.name)",
        "this.escapeHomeRankingText(tag.description || '')",
        "this.escapeHomeRankingText(image.pid || '')",
        "this.escapeHomeRankingText(image.description || '无')",
        "this.escapeHomeRankingText(value)",
    ):
        assert expression in ui_source

    assert '<div class="list-item-name">${group.name}</div>' not in ui_source
    assert '<div class="list-item-name">${character.name}</div>' not in ui_source
    assert '<div class="list-item-name">${tag.name}</div>' not in ui_source
    assert '<p>${image.description || \'无\'}</p>' not in ui_source


def test_temp_filenames_are_escaped_and_not_embedded_in_inline_handlers():
    source = UPLOAD_JS.read_text(encoding="utf-8")

    assert "const escapedName = this.escapeHtml(imageName)" in source
    assert '<div class="temp-image-name">${escapedName}</div>' in source
    assert "item.querySelector('.temp-image-submit')?.addEventListener" in source
    assert "document.getElementById('temp-upload-delete')?.addEventListener" in source
    assert "onclick=\"upload.uploadTempImage('${encodedName}')\"" not in source
    assert "onclick=\"upload.deleteTempFile('${encodedName}')\"" not in source
    assert "onclick=\"upload.deleteTempImageFromModal('${imageNameEncoded}')\"" not in source


def test_page_features_are_lazy_loaded_and_deduplicated():
    auth_source = AUTH_JS.read_text(encoding="utf-8")
    ui_source = _ui_source()
    core_script_block = re.search(
        r"const scripts = \[(.*?)\];", auth_source, flags=re.DOTALL
    )

    assert core_script_block is not None
    core_scripts = core_script_block.group(1)
    assert "/static/js/upload.js" not in core_scripts
    assert "/static/js/emoji-library.js" not in core_scripts
    assert "/static/js/upload.js?v=20260820d" in auth_source
    assert "/static/js/emoji-library.js?v=20260820i" in auth_source
    assert "if (this.featureLoadPromises[name])" in auth_source
    assert "this.featureLoadPromises[name] = loadPromise" in auth_source
    assert "delete this.featureLoadPromises[name]" in auth_source

    upload_load = ui_source.index("await window.auth.loadFeature('upload')")
    upload_data = ui_source.index("await this.loadUploadData()", upload_load)
    emoji_load = ui_source.index("await window.auth.loadFeature('emoji')")
    emoji_init = ui_source.index("await emojiLibrary.init()", emoji_load)
    assert upload_load < upload_data
    assert emoji_load < emoji_init
    assert "if (!emojiLibrary.initialized)" in ui_source
    assert "case 'emoji-upload':" in ui_source
    assert "pageElement.inert = true" in ui_source
    assert "pageElement.dataset.featureLoadError = featureKey" in ui_source
    assert "retryFailedFeature" in ui_source


def test_image_search_options_load_on_first_image_tab_visit():
    ui_source = _ui_source()
    image_tab = ui_source.split("case 'image-list':", 1)[1].split("break;", 1)[0]
    option_loader = ui_source.split("async loadImageSearchOptions()", 1)[1].split(
        "initSearchableSelect(config)", 1
    )[0]

    assert "this.loadImages()" in image_tab
    assert "this.loadImageSearchOptions()" in image_tab
    assert "Promise.all([" in option_loader
    assert "this.loadGroupsData()" in option_loader
    assert "this.loadCharactersData()" in option_loader
    assert "this.filteredCharacters = characters" in option_loader
    assert "this.renderGroupDropdown()" in option_loader
    assert "this.renderCharacterDropdown()" in option_loader


def test_searchable_select_initialization_is_idempotent():
    ui_source = _ui_source()
    initializer = ui_source.split("initSearchableSelect(config)", 1)[1].split(
        "filterSearchableOptions(config)", 1
    )[0]

    assert "if (input._searchableSelectInitialized) return" in initializer
    assert "input._searchableSelectInitialized = true" in initializer
    assert "this.filterSearchableOptions(input._config)" in initializer


def test_script_loader_reuses_existing_nodes_and_removes_failed_nodes():
    source = AUTH_JS.read_text(encoding="utf-8")

    assert "Array.from(document.scripts).find" in source
    assert "script.dataset.loaded = 'true'" in source
    assert "script.remove();" in source


def test_home_modules_are_parallel_and_notifications_are_off_critical_path():
    main_source = MAIN_JS.read_text(encoding="utf-8")
    auth_source = AUTH_JS.read_text(encoding="utf-8")

    assert "Promise.allSettled(homeModules.map" in main_source
    assert "await Promise.allSettled(homeModules.map" not in main_source
    assert "ui.loadSystemStatus()" in main_source
    assert "ui.loadHomeGroupChips()" in main_source
    assert "ui.loadHomeRankings()" in main_source
    assert "await this.checkNotifications()" not in auth_source
    assert "this.scheduleNotificationCheck()" in auth_source
    assert "requestIdleCallback" in auth_source
