from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def test_duplicate_maintenance_reuses_existing_comparison_dialog():
    html = (PROJECT_ROOT / "static/index.html").read_text(encoding="utf-8")
    api_source = (PROJECT_ROOT / "static/js/api.js").read_text(encoding="utf-8")
    ui_source = (PROJECT_ROOT / "static/js/ui.js").read_text(encoding="utf-8")

    assert 'id="scan-duplicates-button"' in html
    assert "api.scanExistingDuplicates(25, excludedPairs)" in ui_source
    assert "uploadFeature.resolveDuplicateChoice" in ui_source
    assert "if (decision.action === 'later')" in ui_source
    assert "excludedPairs.push(group.image_ids || [])" in ui_source
    assert "api.resolveExistingDuplicates" in ui_source
    assert "/system/duplicates/scan" in api_source
    assert "'/system/duplicates/resolve'" in api_source
    assert "删除" in ui_source
    for label in ("校验文件", "补缩略图", "整理孤立文件", "查重", "归档缺失图片", "删除档案"):
        assert label in html
    assert "async function deleteInvalidRecords()" in ui_source
    assert "api.cleanupOrphaned('delete')" in ui_source
    assert "此操作无法恢复" in ui_source
