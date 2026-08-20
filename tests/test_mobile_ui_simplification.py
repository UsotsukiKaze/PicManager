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
    assert ".home-stat-hint," in mobile


def test_mobile_modals_are_safe_area_aware_bottom_sheets():
    mobile = STYLE.split("/* Mobile-focused simplification", 1)[1]
    assert "max-height: calc(100dvh - 34px)" in mobile
    assert "border-radius: 18px 18px 0 0" in mobile
    assert "env(safe-area-inset-bottom)" in mobile
    assert ".tag-picker .form-actions" in mobile


def test_small_phone_cards_drop_secondary_metadata_and_use_one_column():
    small = STYLE.split("@media (max-width: 420px)", 1)[1]
    assert "grid-template-columns: 1fr" in small
    assert ".image-card-id," in small
    assert ".image-card-pid" in small


def test_motion_reduction_covers_page_card_modal_and_orbit_animations():
    reduced = STYLE.rsplit("@media (prefers-reduced-motion: reduce)", 1)[1]
    for selector in (".image-card", ".modal", ".page-enter", ".tab-enter", ".home-orbit", ".orbit-chip"):
        assert selector in reduced
