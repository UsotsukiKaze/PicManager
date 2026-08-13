from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def test_avatar_frontend_has_bounded_defaults_and_recoverable_errors():
    api_source = (PROJECT_ROOT / "static/js/api.js").read_text(encoding="utf-8")
    ui_source = (PROJECT_ROOT / "static/js/ui.js").read_text(encoding="utf-8")

    assert "const limit = options.limit ?? 200" in api_source
    assert api_source.count("params.set('limit', options.limit ?? 200)") == 2
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
