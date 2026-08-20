from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def test_duplicate_choice_uses_signed_resolve_without_reuploading_file():
    api_source = (PROJECT_ROOT / "static/js/api.js").read_text(encoding="utf-8")
    upload_source = (PROJECT_ROOT / "static/js/upload.js").read_text(encoding="utf-8")

    method = upload_source.split("async uploadWithDuplicateChoice", 1)[1].split("async uploadSingleImage", 1)[0]
    assert "firstResult?.status !== 'duplicate'" in method
    assert "api.resolveDuplicateImage(firstResult.duplicate_token, keep, decision.metadataSources" in method
    assert method.count("api.uploadSingleImage(") == 1
    assert "await api.resolveDuplicateImage(firstResult.duplicate_token, 'cancel')" in method
    assert "'/upload/duplicates/resolve'" in api_source


def test_duplicate_dialog_serializes_batch_choices_and_handles_modal_close():
    upload_source = (PROJECT_ROOT / "static/js/upload.js").read_text(encoding="utf-8")
    ui_source = "\n".join(
        (PROJECT_ROOT / f"static/js/{name}").read_text(encoding="utf-8")
        for name in ("modal.js", "ui.js")
    )

    assert "this.duplicateChoiceQueue.then(choose, choose)" in upload_source
    assert "layer._onModalClose" in upload_source
    assert "typeof activeLayer?._onModalClose === 'function'" in ui_source
    assert "duplicate-compare-grid" in upload_source
    assert "文件" in upload_source and "大小" in upload_source and "分辨率" in upload_source
    assert "特征标签" in upload_source and "描述" in upload_source
    assert ">暂不处理<" in upload_source
    assert ">保存全部<" in upload_source
    assert ">合并检查<" in upload_source
    assert ">确认合并<" in upload_source
    assert "data-merge-field" in upload_source
    assert "mergedDuplicateItem(items, layer)" in upload_source
    assert "renderMergedDuplicatePreview(items, layer)" in upload_source
    assert "修改后保留图片" in upload_source
    assert "永久删除另一份原图及缩略图" in upload_source
