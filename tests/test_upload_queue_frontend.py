from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
INDEX = (PROJECT_ROOT / "static" / "index.html").read_text(encoding="utf-8")
AUTH = (PROJECT_ROOT / "static" / "js" / "auth.js").read_text(encoding="utf-8")
QUEUE = (PROJECT_ROOT / "static" / "js" / "upload-queue.js").read_text(encoding="utf-8")
STYLE = (PROJECT_ROOT / "static" / "css" / "style.css").read_text(encoding="utf-8")
UPLOAD = (PROJECT_ROOT / "static" / "js" / "upload.js").read_text(encoding="utf-8")


def test_global_upload_queue_is_loaded_with_the_application_shell():
    assert 'id="upload-queue-dock"' in INDEX
    assert 'id="upload-queue-toggle"' in INDEX
    assert 'id="upload-queue-panel"' in INDEX
    assert "/static/js/upload-queue.js" in AUTH
    assert "window.uploadQueue = new UploadQueueDock()" in QUEUE
    assert (PROJECT_ROOT / "tests" / "upload_queue_smoke.js").is_file()


def test_upload_queue_supports_progress_attention_retry_and_unload_protection():
    assert "ACTIVE_STATES" in QUEUE
    assert "status === 'attention'" in QUEUE
    assert "async retry(taskId)" in QUEUE
    assert "window.addEventListener('beforeunload'" in QUEUE
    assert 'aria-live="polite"' in INDEX


def test_queue_dock_has_hover_desktop_tap_mobile_and_reduced_motion_rules():
    assert "@media (hover: hover) and (pointer: fine)" in STYLE
    assert ".upload-queue-dock:hover .upload-queue-panel" in STYLE
    assert "@media (max-width: 768px)" in STYLE
    assert "@media (prefers-reduced-motion: reduce)" in STYLE


def test_single_and_batch_uploads_report_to_the_global_queue():
    assert "detachSingleUploadForQueue()" in UPLOAD
    assert "上传任务已收进队列" in UPLOAD
    assert "stage => this.queueStage(context.taskId, stage)" in UPLOAD
    assert "item.queueTaskId = uploadQueue.add" in UPLOAD
    assert "batchElement.dataset.queueCollapsed = 'true'" in UPLOAD
    assert '.batch-item[data-queue-collapsed="true"]' in STYLE
