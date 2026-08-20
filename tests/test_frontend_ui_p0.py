import re
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
INDEX_HTML = (PROJECT_ROOT / "static" / "index.html").read_text(encoding="utf-8")
UI_JS = "\n".join(
    (PROJECT_ROOT / "static" / "js" / name).read_text(encoding="utf-8")
    for name in ("entity-cache.js", "search-selector.js", "image-list.js", "modal.js", "ui.js")
)
UPLOAD_JS = (PROJECT_ROOT / "static" / "js" / "upload.js").read_text(encoding="utf-8")
STYLE_CSS = (PROJECT_ROOT / "static" / "css" / "style.css").read_text(encoding="utf-8")


def test_mobile_navigation_has_an_explicit_home_destination():
    assert 'class="menu-item menu-item-home active" data-page="home"' in INDEX_HTML
    assert '.menu-item[data-page="home"] .menu-icon' in STYLE_CSS


def test_upload_dropzones_and_image_cards_use_keyboard_native_controls():
    assert re.search(r'<button[^>]+id="single-upload-area"', INDEX_HTML)
    assert re.search(r'<button[^>]+id="batch-upload-area"', INDEX_HTML)
    assert 'aria-describedby="single-upload-formats"' in INDEX_HTML
    assert 'aria-describedby="batch-upload-hint"' in INDEX_HTML
    assert 'class="image-card-open"' in UI_JS
    assert 'type="button" class="image-card-reveal"' in UI_JS
    assert '.image-card-open:focus-visible' in STYLE_CSS


def test_batch_queue_has_stable_items_retry_and_controlled_three_worker_pool():
    process_batch = UPLOAD_JS.split("async processBatchUpload", 1)[1].split("clearSingleUpload()", 1)[0]
    assert "this.batchWorkerCount = 3" in UPLOAD_JS
    assert 'data-batch-id="${item.id}"' in UPLOAD_JS
    assert "if (this.batchSubmitting) return" in UPLOAD_JS
    assert "retryBatchItem(itemId)" in UPLOAD_JS
    assert "clearSuccessfulBatchItems()" in UPLOAD_JS
    assert "Math.min(this.batchWorkerCount, pendingItems.length)" in UPLOAD_JS
    assert "Promise.all(Array.from({ length: activeWorkerCount }, () => worker()))" in UPLOAD_JS
    assert "this.batchFiles = []" not in process_batch


def test_failed_uploads_remain_retryable_and_completed_items_are_explicitly_cleared():
    assert "item.status = 'failed'" in UPLOAD_JS
    assert "item.status === 'ready' || item.status === 'failed'" in UPLOAD_JS
    assert "item.status === 'success' || item.status === 'pending-review'" in UPLOAD_JS
    assert 'class="btn btn-primary btn-sm batch-retry"' in UPLOAD_JS
    assert "if (successCount + pendingCount > 0)" in UPLOAD_JS


def test_r16_and_r18_are_hidden_until_each_card_or_detail_is_revealed():
    assert "rating === 'r16' || rating === 'r18'" in UI_JS
    assert "is-age-restricted is-${rating}" in UI_JS
    assert "data-sensitive-src" in UI_JS
    assert "toggleAgeReveal(card" in UI_JS
    assert "toggleDetailAgeReveal(button)" in UI_JS
    assert '.image-card.is-r18:not(.age-revealed) .image-card-img' in STYLE_CSS
    assert '.image-detail-media.is-r18:not(.age-revealed) img' in STYLE_CSS


def test_modal_has_dialog_semantics_focus_restore_trap_and_background_inert():
    assert 'role="dialog"' in INDEX_HTML
    assert 'aria-modal="true"' in INDEX_HTML
    assert 'aria-labelledby="modal-title"' in INDEX_HTML
    assert 'aria-label="关闭弹窗"' in INDEX_HTML
    assert "this.modalPreviousFocus = document.activeElement" in UI_JS
    assert "if (e.key === 'Tab' && modalVisible) this.trapModalFocus(e)" in UI_JS
    assert "lastElementChild" in UI_JS
    assert "setAttribute('inert', '')" in UI_JS
    assert "removeAttribute('inert')" in UI_JS


def test_image_search_replaces_stale_results_with_busy_and_retryable_error_states():
    load_images = UI_JS.split("async loadImages(params = undefined)", 1)[1].split("async loadFeatureTagsData", 1)[0]
    assert "const requestId = ++this.imageLoadRequestId" in load_images
    assert "grid.setAttribute('aria-busy', 'true')" in load_images
    assert "image-grid-loading" in load_images
    assert "if (requestId !== this.imageLoadRequestId) return" in load_images
    assert "if (requestId === this.imageLoadRequestId)" in load_images
    assert "grid.setAttribute('aria-busy', 'false')" in load_images
    assert "image-grid-error" in load_images
    assert 'onclick="ui.loadImages(null)"' in load_images


def test_home_orbit_chips_expand_and_wrap_instead_of_truncating():
    orbit_rule = STYLE_CSS.split(".orbit-chip {", 1)[1].split("}", 1)[0]
    label_rule = STYLE_CSS.split(".orbit-chip-label {", 1)[1].split("}", 1)[0]

    assert "width: max-content" in orbit_rule
    assert "max-width: min(240px, calc(100% - 56px))" in orbit_rule
    assert "text-overflow: ellipsis" not in orbit_rule
    assert "white-space: nowrap" not in orbit_rule
    assert "white-space: normal" in label_rule
    assert "overflow-wrap: anywhere" in label_rule
    assert "label.className = 'orbit-chip-label'" in UI_JS


def test_image_derivative_urls_change_when_image_content_version_changes():
    assert "getImageVersion(image)" in UI_JS
    assert "image.updated_at || image.file_checked_at || image.created_at" in UI_JS
    assert "?v=${this.getImageVersion(image)}" in UI_JS
    assert "encodeURIComponent(image.image_id)" in UI_JS
    assert "/resource/previews/${encodeURIComponent(image.image_id)}.webp" in UI_JS
    assert "restricted ? this.getThumbnailUrl(image) : this.getPreviewUrl(image)" in UI_JS
