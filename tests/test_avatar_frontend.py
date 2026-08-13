from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def test_frontend_lists_negotiate_bounded_pages_and_avatar_errors_recover():
    api_source = (PROJECT_ROOT / "static/js/api.js").read_text(encoding="utf-8")
    ui_source = (PROJECT_ROOT / "static/js/ui.js").read_text(encoding="utf-8")

    assert "async requestAllPages(endpoint, baseParams = {}, options = {})" in api_source
    assert "if (error.status === 422 && items.length === 0 && pageSize > 1)" in api_source
    assert "return this.requestAllPages('/characters/', params)" in api_source
    assert "return this.requestAllPages('/feature-tags/')" in api_source
    assert "return this.requestAllPages('/emotion-tags/')" in api_source
    assert "?? 200" not in api_source
    assert "const timeoutMs = options.timeoutMs ?? 30000" in api_source
    assert "signal: controller.signal" in api_source
    assert "头像上传超时，请检查网络后重试" in api_source
    assert "canvas.width = 512" in ui_source
    assert "canvas.toBlob(resolve, 'image/webp', 0.88)" in ui_source
    assert "canvas.toBlob(resolve, 'image/png')" in ui_source
    assert "state.abortController = new AbortController()" in ui_source
    assert "this.avatarCropState?.abortController?.abort()" in ui_source
    assert "头像图片解码失败" in ui_source
    assert "头像仍在解码" in ui_source
    assert "button.disabled = false" in ui_source
