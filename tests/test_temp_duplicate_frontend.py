from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def test_temp_duplicate_scan_has_dedicated_file_choice_and_metadata_editor():
    html = (PROJECT_ROOT / "static/index.html").read_text(encoding="utf-8")
    api_source = (PROJECT_ROOT / "static/js/api.js").read_text(encoding="utf-8")
    upload_source = (PROJECT_ROOT / "static/js/upload.js").read_text(encoding="utf-8")

    assert 'id="scan-temp-duplicates-button"' in html
    assert ">扫描重复<" in html
    assert "/upload/temp-duplicates/scan" in api_source
    assert "/upload/temp-duplicates/resolve" in api_source
    assert "showTempDuplicateEditor(result, catalogs)" in upload_source
    assert 'name="temp-duplicate-keep" value="temp"' in upload_source
    assert 'name="temp-duplicate-keep" value="existing"' in upload_source
    assert "Temp 文件名" in upload_source
    assert "data-copy-temp-filename" in upload_source
    assert "data-use-temp-pid" in upload_source
    assert "temp-duplicate-tag-selector" in upload_source
    assert "合并后信息" in upload_source
    assert "api.scanTempDuplicates(1)" in upload_source
    assert "api.resolveTempDuplicate" in upload_source
