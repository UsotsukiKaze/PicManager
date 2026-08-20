from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
API = (PROJECT_ROOT / "static" / "js" / "api.js").read_text(encoding="utf-8")
EMOJI = (PROJECT_ROOT / "static" / "js" / "emoji-library.js").read_text(encoding="utf-8")
STYLE = (PROJECT_ROOT / "static" / "css" / "style.css").read_text(encoding="utf-8")


def test_emoji_cards_open_details_without_inline_edit_or_delete_actions():
    render_grid = EMOJI.split("renderGrid(emojis)", 1)[1].split("async showEmojiDetail", 1)[0]
    assert 'class="image-card-open"' in render_grid
    assert "this.showEmojiDetail(card.dataset.emojiId)" in render_grid
    assert "showEditEmojiModal" not in render_grid
    assert "deleteEmoji" not in render_grid
    assert "emoji-card-actions" not in render_grid


def test_emoji_detail_contains_download_metadata_and_admin_actions():
    detail = EMOJI.split("async showEmojiDetail", 1)[1].split("async showEditEmojiModal", 1)[0]
    assert "api.getEmoji(id)" in detail
    assert "表情包详情" in detail
    assert "下载表情包" in detail
    assert "showEditEmojiModal" in detail
    assert "deleteEmoji" in detail
    assert "window.auth?.isAdmin?.()" in detail
    assert "renderDetailChips(emoji.emotions, 'emotion')" in detail
    assert ".emoji-detail-media img" in STYLE
    assert "'gif' ? 'is-gif' : ''" in detail
    assert ".emoji-detail-media.is-gif img" in STYLE
    assert "max-width: min(100%, 420px)" in STYLE


def test_emoji_download_uses_authenticated_download_endpoint():
    assert "getEmojiDownloadUrl(id)" in API
    assert "`${this.baseURL}/emojis/${encodeURIComponent(id)}/download`" in API
    assert "link.href = api.getEmojiDownloadUrl(id)" in EMOJI
    assert "link.download = ''" in EMOJI
