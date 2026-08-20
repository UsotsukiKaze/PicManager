from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
INDEX = (PROJECT_ROOT / "static" / "index.html").read_text(encoding="utf-8")
STYLE = (PROJECT_ROOT / "static" / "css" / "style.css").read_text(encoding="utf-8")


def test_mobile_header_keeps_actions_accessible_but_removes_labels_and_wrap():
    assert 'aria-label="打开个人资料"' in INDEX
    assert 'aria-label="退出登录"' in INDEX
    mobile = STYLE.split("/* Mobile-focused simplification", 1)[1]
    assert ".top-user-bar" in mobile and "flex-wrap: nowrap" in mobile
    assert ".header-link" in mobile and "font-size: 0" in mobile
    assert ".user-role-small" in mobile


def test_mobile_hides_decorative_or_desktop_maintenance_surfaces():
    assert INDEX.count("mobile-hide") >= 3
    mobile = STYLE.split("/* Mobile-focused simplification", 1)[1]
    assert ".mobile-hide," in mobile
    assert ".admin-maintenance" in mobile
    assert ".home-orbit," in mobile


def test_mobile_active_navigation_keeps_a_visible_colored_icon():
    mobile = STYLE.split("/* Mobile-focused simplification", 1)[1]
    assert ".sidebar-menu .menu-indicator" in mobile
    assert ".sidebar-menu .menu-item.active .menu-icon" in mobile
    assert "background-color: var(--primary-color)" in mobile
    assert "background: rgba(0, 122, 255, 0.1)" in mobile


def test_mobile_home_title_breaks_and_metrics_stay_in_one_compact_row():
    mobile = STYLE.split("/* Mobile-focused simplification", 1)[1]
    assert 'class="home-title-name"' in INDEX
    assert ".home-title-name" in mobile
    assert "display: block" in mobile.split(".home-title-name", 1)[1].split("}", 1)[0]
    metrics = mobile.split(".home-metrics {", 1)[1].split("}", 1)[0]
    assert "grid-template-columns: repeat(3, minmax(0, 1fr))" in metrics
    assert "min-height: 92px" in mobile
    assert "font-size: clamp(20px, 6vw, 26px)" in mobile


def test_home_hero_replaces_decorative_spectrum_with_emphasized_metrics():
    mobile = STYLE.split("/* Mobile-focused simplification", 1)[1]
    assert "这里可以快速查看图片数量" not in INDEX
    assert '>查看图片</button>' not in INDEX
    assert '>去上传</button>' not in INDEX
    assert "home-hero-spectrum" not in INDEX
    assert "home-spectrum-line" not in STYLE
    assert 'class="home-metrics"' in INDEX
    assert INDEX.count("home-metric-card home-metric-") == 3
    for element_id in ("home-total-images", "home-total-emojis", "home-total-groups", "home-total-characters"):
        assert INDEX.count(f'id="{element_id}"') == 1
    assert "font-variant-numeric: tabular-nums" in STYLE
    desktop_metrics = STYLE.split(".home-metrics {", 1)[1].split("}", 1)[0]
    desktop_numbers = STYLE.split(".home-metric-card strong {", 1)[1].split("}", 1)[0]
    assert "margin-top: 12px" in desktop_metrics
    assert "font-size: clamp(28px, 2.8vw, 40px)" in desktop_numbers
    assert "font-weight: 700" in desktop_numbers
    metric = mobile.split(".home-metric-card {", 1)[1].split("}", 1)[0]
    assert "min-height: 92px" in metric


def test_mobile_modals_are_safe_area_aware_bottom_sheets():
    mobile = STYLE.split("/* Mobile-focused simplification", 1)[1]
    assert "max-height: calc(100dvh - 34px)" in mobile
    assert "border-radius: 18px 18px 0 0" in mobile
    assert "env(safe-area-inset-bottom)" in mobile
    assert ".tag-picker .form-actions" in mobile


def test_small_phone_image_management_keeps_two_columns_and_compacts_cards():
    small = STYLE.split("@media (max-width: 420px)", 1)[1]
    image_grid = small.split(".image-grid {", 1)[1].split("}", 1)[0]
    temp_grid = small.split(".temp-image-grid {", 1)[1].split("}", 1)[0]
    assert "grid-template-columns: repeat(2, minmax(0, 1fr))" in image_grid
    assert "gap: 8px" in image_grid
    assert "grid-template-columns: 1fr" in temp_grid
    mobile_info = small.split(".image-card-info {", 1)[1].split("}", 1)[0]
    mobile_characters = small.split(".image-card-characters {", 1)[1].split("}", 1)[0]
    assert "height: 42px" in mobile_info
    assert "min-height: 42px" in mobile_info
    assert "white-space: nowrap" in mobile_characters
    assert "text-overflow: ellipsis" in mobile_characters
    hidden_id = small.split(".image-card-id {", 1)[1].split("}", 1)[0]
    mobile_pid = small.split(".image-card-pid {", 1)[1].split("}", 1)[0]
    assert "display: none" in hidden_id
    assert "display: block" in mobile_pid
    assert "font-size: 10px" in mobile_pid
    assert "text-overflow: ellipsis" in mobile_pid


def test_desktop_image_cards_use_fixed_metadata_height_and_ellipsis():
    card_refresh = STYLE.split(".emoji-detail-media.is-gif img", 1)[1].split("@media (max-width: 640px)", 1)[0]
    card_info = card_refresh.split(".image-card-info {", 1)[1].split("}", 1)[0]
    truncated_text = card_refresh.split(".image-card-id,", 1)[1].split("}", 1)[0]
    assert "height: 88px" in card_info
    assert "overflow: hidden" in card_info
    assert ".image-card-characters" in truncated_text
    assert ".image-card-pid" in truncated_text
    assert "white-space: nowrap" in truncated_text
    assert "text-overflow: ellipsis" in truncated_text


def test_motion_reduction_covers_page_card_modal_and_orbit_animations():
    reduced = STYLE.rsplit("@media (prefers-reduced-motion: reduce)", 1)[1]
    for selector in (".image-card", ".modal", ".page-enter", ".tab-enter", ".home-orbit", ".orbit-chip"):
        assert selector in reduced
