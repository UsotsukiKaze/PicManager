from pathlib import Path

import main
from app.config import Settings


def test_legacy_homepage_routes_are_removed_but_kazeapps_auth_bridge_remains():
    paths = {getattr(route, "path", "") for route in main.app.routes}

    assert "/home" not in paths
    assert not any(path.startswith("/api/guestbook") for path in paths)
    assert "/api/integrations/kaze-apps/root-session" in paths


def test_picmanager_shell_does_not_reference_removed_homepage_assets():
    source = (Path(__file__).resolve().parents[1] / "static" / "index.html").read_text(encoding="utf-8")

    assert "/static/homepage/" not in source


def test_picmanager_default_hosts_exclude_kazeapps_domains():
    hosts = {
        host.strip()
        for host in Settings.model_fields["TRUSTED_HOSTS"].default.split(",")
        if host.strip()
    }

    assert "pic.usotsuki-kaze.com" in hosts
    assert "usotsuki-kaze.com" not in hosts
    assert "www.usotsuki-kaze.com" not in hosts
    assert "apps.usotsuki-kaze.com" not in hosts
