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
    assert "归档" in ui_source
