from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def test_duplicate_choice_uses_signed_resolve_without_reuploading_file():
    api_source = (PROJECT_ROOT / "static/js/api.js").read_text(encoding="utf-8")
    upload_source = (PROJECT_ROOT / "static/js/upload.js").read_text(encoding="utf-8")

    method = upload_source.split("async uploadWithDuplicateChoice", 1)[1].split("async uploadSingleImage", 1)[0]
    assert "firstResult?.status !== 'duplicate'" in method
    assert "api.resolveDuplicateImage(firstResult.duplicate_token, duplicateKeep)" in method
    assert method.count("api.uploadSingleImage(") == 1
    assert "await api.resolveDuplicateImage(firstResult.duplicate_token, 'cancel')" in method
    assert "'/upload/duplicates/resolve'" in api_source


def test_duplicate_dialog_serializes_batch_choices_and_handles_modal_close():
    upload_source = (PROJECT_ROOT / "static/js/upload.js").read_text(encoding="utf-8")
    ui_source = (PROJECT_ROOT / "static/js/ui.js").read_text(encoding="utf-8")

    assert "this.duplicateChoiceQueue.then(choose, choose)" in upload_source
    assert "layer._onModalClose" in upload_source
    assert "typeof activeLayer?._onModalClose === 'function'" in ui_source
    assert "重复的现有图片将归档，但不会物理删除原文件" in upload_source
