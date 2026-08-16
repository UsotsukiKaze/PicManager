import re
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
INDEX_HTML = PROJECT_ROOT / "static" / "index.html"
AUTH_JS = PROJECT_ROOT / "static" / "js" / "auth.js"
MAIN_JS = PROJECT_ROOT / "static" / "js" / "main.js"
UI_JS = PROJECT_ROOT / "static" / "js" / "ui.js"


def test_anonymous_shell_only_eagerly_loads_auth_bootstrap():
    html = INDEX_HTML.read_text(encoding="utf-8")
    eager_scripts = re.findall(r'<script\b[^>]*\bsrc="([^"]+)"', html)

    assert eager_scripts == ["/static/js/auth.js?v=20260816a"]
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
        "/static/css/style.css?v=20260816a",
        "/static/js/api.js?v=20260816a",
        "/static/js/ui.js?v=20260816a",
        "/static/js/main.js?v=20260812c",
    ):
        assert asset in source

    assert "document.documentElement.classList.remove('app-booting')" in source
    assert "await this.waitForDocumentBody()" in source
    assert "const scriptsReady = Promise.all(scripts.map(src => this.loadScript(src)))" in source
    assert "await scriptsReady" in source
    assert "for (const src of scripts)" not in source
    assert "script.async = false" in source


def test_page_features_are_lazy_loaded_and_deduplicated():
    auth_source = AUTH_JS.read_text(encoding="utf-8")
    ui_source = UI_JS.read_text(encoding="utf-8")
    core_script_block = re.search(
        r"const scripts = \[(.*?)\];", auth_source, flags=re.DOTALL
    )

    assert core_script_block is not None
    core_scripts = core_script_block.group(1)
    assert "/static/js/upload.js" not in core_scripts
    assert "/static/js/emoji-library.js" not in core_scripts
    assert "/static/js/upload.js?v=20260815a" in auth_source
    assert "/static/js/emoji-library.js?v=20260812a" in auth_source
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
