from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def test_duplicate_maintenance_reuses_existing_comparison_dialog():
    html = (PROJECT_ROOT / "static/index.html").read_text(encoding="utf-8")
    api_source = (PROJECT_ROOT / "static/js/api.js").read_text(encoding="utf-8")
    ui_source = (PROJECT_ROOT / "static/js/ui.js").read_text(encoding="utf-8")

    assert 'id="local-check-button"' in html
    shell_source = (PROJECT_ROOT / "static/js/workspace-shell.js").read_text(encoding="utf-8")
    assert "scanExistingDuplicates(true)" in shell_source
    assert "api.scanExistingDuplicates(25, excludedPairs, localValidation)" in ui_source
    assert "uploadFeature.resolveDuplicateChoice" in ui_source
    assert "if (decision.action === 'later')" in ui_source
    assert "excludedPairs.push(group.image_ids || [])" in ui_source
    assert "api.resolveExistingDuplicates" in ui_source
    assert "/system/duplicates/scan" in api_source
    assert "'/system/duplicates/resolve'" in api_source
    assert "删除" in ui_source
    for label in ("本地校验", "Pixiv 校验", "疑似重复图片", "删除档案"):
        assert label in html
    assert "async function deleteInvalidRecords()" in ui_source
    assert "api.cleanupOrphaned('delete')" in ui_source
    assert "此操作无法恢复" in ui_source
