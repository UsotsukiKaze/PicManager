from html.parser import HTMLParser
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
INDEX = (PROJECT_ROOT / "static" / "index.html").read_text(encoding="utf-8")
QUERY = (PROJECT_ROOT / "static" / "js" / "query-panel.js").read_text(encoding="utf-8")
AUTH = (PROJECT_ROOT / "static" / "js" / "auth.js").read_text(encoding="utf-8")
STYLE = (PROJECT_ROOT / "static" / "css" / "style.css").read_text(encoding="utf-8")


class BalancedHTML(HTMLParser):
    void = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "param", "source", "track", "wbr"}

    def __init__(self):
        super().__init__()
        self.stack = []

    def handle_starttag(self, tag, attrs):
        if tag not in self.void:
            self.stack.append(tag)

    def handle_endtag(self, tag):
        assert self.stack, f"unexpected closing tag: {tag}"
        current = self.stack.pop()
        assert current == tag, f"closed {tag} while {current} was open"


def test_management_and_emoji_queries_are_collapsed_by_default():
    for panel_id in (
        "image-search-panel",
        "group-query-panel",
        "character-query-panel",
        "feature-tag-query-panel",
        "emoji-query-panel",
    ):
        assert f'id="{panel_id}" aria-hidden="true"' in INDEX
        assert f'data-query-toggle="{panel_id}"' in INDEX
    assert "需要时展开，不占用列表空间" not in INDEX
    assert '<span>查询</span>' not in INDEX
    assert INDEX.count('class="query-icon"') == 5
    assert INDEX.count('aria-label="打开') >= 5
    assert INDEX.count('class="entity-query-control"') == 3
    assert STYLE.count(".entity-query-control .compact-query-panel") >= 2
    assert "transform: translateX(8px)" in STYLE
    assert "max-width: 440px" in STYLE
    toolbar_start = INDEX.index('class="query-toolbar image-filter-toolbar"')
    panel_start = INDEX.index('id="image-search-panel"')
    assert toolbar_start < INDEX.index('id="search-age-rating"') < panel_start
    assert ".image-filter-toolbar" in STYLE
    assert "/static/js/query-panel.js" in AUTH


def test_query_controller_tracks_active_filters_mobile_apply_and_keyboard_close():
    assert "fieldHasValue(field)" in QUERY
    assert "data-query-count" in INDEX
    assert "collapseAfterApply(panelId)" in QUERY
    assert "window.matchMedia('(max-width: 768px)')" in QUERY
    assert "event.key !== 'Escape'" in QUERY
    assert ".query-panel.is-expanded" in STYLE
    assert "prefers-reduced-motion: reduce" in STYLE


def test_index_remains_balanced_after_query_toolbar_refactor():
    parser = BalancedHTML()
    parser.feed(INDEX)
    assert parser.stack == []
