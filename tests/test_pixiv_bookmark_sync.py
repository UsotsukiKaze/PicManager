from datetime import datetime, timedelta

import pytest

from test_pixiv_ol import environment, artwork
from app import models
from app.integrations.pixiv_ol import bookmarks, service
from app.integrations.pixiv_ol.provider import PixivError, Provider


class Remote:
    def __init__(self):
        self.public = {"100"}
        self.private = {"101"}
        self.calls = []
        self.unavailable = False
        self.fail_private = False

    def cursor(self, url):
        return Provider.cursor(url)

    def close(self):
        pass

    def call(self, method, **params):
        self.calls.append((method, params))
        if method == "user_bookmarks_illust":
            if self.fail_private and params["restrict"] == "private":
                raise PixivError("external_error")
            values = self.public if params["restrict"] == "public" else self.private
            return {"illusts": [artwork(pid) for pid in sorted(values)], "next_url": None}
        if method == "illust_bookmark_detail":
            if self.unavailable:
                raise PixivError("access_denied")
            pid = params["illust_id"]
            return {
                "bookmark_detail": {
                    "is_bookmarked": pid in self.public | self.private,
                    "restrict": "public" if pid in self.public else "private",
                }
            }
        if method == "illust_bookmark_add":
            (self.public if params["restrict"] == "public" else self.private).add(params["illust_id"])
        elif method == "illust_bookmark_delete":
            self.public.discard(params["illust_id"])
            self.private.discard(params["illust_id"])
        return {}


def enable(context):
    with context() as db:
        account = db.get(models.PixivAccount, 1)
        account.preferences = {**account.preferences, "bookmark_sync": True}


def test_settings_status_counts_only_current_account_and_intent_version(environment):
    context, client, _ = environment
    # Settings load this endpoint even before bookmark sync is enabled.
    response = client.get("/api/pixiv-ol/bookmarks/status")
    assert response.status_code == 200
    assert response.json()["pending"] == response.json()["failed"] == 0
    assert response.json()["enabled"] is False
    with context() as db:
        account = db.get(models.PixivAccount, 1)
        for pid, revision, version, tasks in (
            ("100", "rev", 2, [(1, "failed"), (2, "queued")]),
            ("101", "rev", 1, [(1, "failed")]),
            ("102", "rev", 1, [(1, "running")]),
            ("103", "other-account", 1, [(1, "failed")]),
            ("104", "other-account", 1, [(1, "queued")]),
        ):
            state = models.PixivBookmarkState(account_revision=revision, pid=pid, version=version)
            db.add(state)
            db.flush()
            for task_version, task_status in tasks:
                db.add(models.PixivBookmarkOutbox(state_id=state.id, version=task_version, status=task_status))
        bookmarks.local_feedback(db, account, "100", True)
    response = client.get("/api/pixiv-ol/bookmarks/status")
    assert response.status_code == 200
    assert response.json()["pending"] == 2
    assert response.json()["failed"] == 1
    assert response.json()["local_count"] == 1


def scan(remote, full=True):
    for _ in range(20):
        result = bookmarks.scan_step(remote, "rev", 1, full=full)
        if not result.get("bookmark_more"):
            return
    pytest.fail("scan did not terminate")


class PagedRemote(Remote):
    def __init__(self):
        super().__init__()
        self.public = {"100", "102", "103", "104", "105"}
        self.private = {"101", "106", "107"}

    def call(self, method, **params):
        if method != "user_bookmarks_illust":
            return super().call(method, **params)
        self.calls.append((method, params))
        restrict = params["restrict"]
        rows = sorted(self.public if restrict == "public" else self.private)
        offset = int(params.get("max_bookmark_id", 0))
        more = offset + 2 < len(rows)
        return {
            "illusts": [artwork(pid) for pid in rows[offset : offset + 2]],
            "next_url": (
                f"https://app-api.pixiv.net/v1/user/bookmarks/illust?user_id=7&restrict={restrict}&filter=for_ios&max_bookmark_id={offset + 2}"
                if more
                else None
            ),
        }


@pytest.mark.parametrize("scope", ["both", "public", "private"])
def test_paginated_bookmarks_complete_selected_scopes_and_report_counts(environment, scope):
    context, client, _ = environment
    remote = PagedRemote()
    response = client.put("/api/pixiv-ol/preferences", json={"bookmark_sync": True, "bookmark_sync_scope": scope})
    assert response.status_code == 200
    bookmarks.scan_step(remote, "rev", 1, full=True)
    with context() as db:
        state = db.get(models.PixivAccount, 1).sync_state["bookmarks"]
        assert not state.get("initial_complete")
        assert state["scan"]["cursor"] == {"max_bookmark_id": "2"}
    scan(remote)
    expected = remote.public | remote.private if scope == "both" else getattr(remote, scope)
    with context() as db:
        assert {r.pid for r in db.query(models.PixivFeedback).filter_by(value="like")} == expected
        state = db.get(models.PixivAccount, 1).sync_state["bookmarks"]
        assert state["initial_complete"] is True
        assert state["completed_scope"] == scope
        assert state["remote_count"] == len(expected)
        assert db.query(models.PixivCartItem).count() == db.query(models.Image).count() == 0
    status = client.get("/api/pixiv-ol/bookmarks/status").json()
    assert status["scope"] == scope
    assert status["public_count"] == (0 if scope == "private" else 5)
    assert status["private_count"] == (0 if scope == "public" else 3)
    assert {params["restrict"] for method, params in remote.calls if method == "user_bookmarks_illust"} == (
        set(("public", "private")) if scope == "both" else {scope}
    )


def test_unknown_pagination_never_completes_scan_or_infers_removals(environment, monkeypatch):
    context, _, _ = environment
    remote = PagedRemote()
    enable(context)
    monkeypatch.setattr(remote, "cursor", lambda _: {})
    with pytest.raises(PixivError, match="bookmark_cursor_invalid"):
        bookmarks.scan_step(remote, "rev", 1, full=True)
    with context() as db:
        state = db.get(models.PixivAccount, 1).sync_state["bookmarks"]
        assert not state.get("initial_complete")
        assert not state.get("last_full")


def test_scope_change_restarts_scan_and_never_removes_excluded_bookmarks(environment):
    context, client, _ = environment
    remote = PagedRemote()
    enable(context)
    scan(remote)
    bookmarks.scan_step(remote, "rev", 1, full=True)
    assert (
        client.put(
            "/api/pixiv-ol/preferences", json={"bookmark_sync": True, "bookmark_sync_scope": "private"}
        ).status_code
        == 200
    )
    with context() as db:
        state = db.get(models.PixivAccount, 1).sync_state["bookmarks"]
        assert state["scan"] is None and state["full_requested"] is True
    remote.calls.clear()
    remote.public.clear()
    scan(remote)
    scan(remote)
    assert {params["restrict"] for method, params in remote.calls if method == "user_bookmarks_illust"} == {"private"}
    with context() as db:
        public = db.query(models.PixivBookmarkState).filter_by(pid="100").one()
        assert public.desired is True and public.missing_scans == 0
        assert db.query(models.PixivFeedback).filter_by(pid="100", value="like").count() == 1


def test_initial_union_preserves_visibility_and_does_not_download_or_cart(environment, monkeypatch):
    context, client, _ = environment
    remote = Remote()
    client.post("/api/pixiv-ol/feedback", json={"pid": "102", "value": "like"})
    enable(context)
    scan(remote)
    monkeypatch.setattr(service, "client_for_job", lambda *args: remote)
    while bookmarks.run_outbox_once():
        pass
    with context() as db:
        assert {r.pid for r in db.query(models.PixivFeedback).filter_by(value="like")} == {"100", "101", "102"}
        assert db.query(models.PixivCartItem).count() == 0
        assert db.query(models.Image).count() == 0
    assert remote.public == {"100"} and remote.private == {"101", "102"}
    assert [p["illust_id"] for method, p in remote.calls if method == "illust_bookmark_add"] == ["102"]


def test_latest_click_wins_and_auto_cart_roundtrip_keeps_provenance(environment, monkeypatch):
    context, client, _ = environment
    remote = Remote()
    enable(context)
    scan(remote)
    with context() as db:
        account = db.get(models.PixivAccount, 1)
        bookmarks.intent(db, account, 1, "103", True, "auto_cart")
    monkeypatch.setattr(service, "client_for_job", lambda *args: remote)
    assert bookmarks.run_outbox_once()
    scan(remote)
    with context() as db:
        assert db.query(models.PixivBookmarkState).filter_by(pid="103").one().source == "auto_cart"
    for value in ("clear", "like", "clear"):
        assert client.post("/api/pixiv-ol/feedback", json={"pid": "103", "value": value}).status_code == 200
    while bookmarks.run_outbox_once():
        pass
    assert "103" not in remote.public | remote.private
    assert len([m for m, _ in remote.calls if m == "illust_bookmark_delete"]) == 1


def test_remote_removal_requires_two_full_successful_scans_and_explicit_detail(environment):
    context, _, _ = environment
    remote = Remote()
    enable(context)
    scan(remote)
    remote.public.clear()
    scan(remote)
    with context() as db:
        assert db.query(models.PixivFeedback).filter_by(pid="100", value="like").count() == 1
    remote.fail_private = True
    with pytest.raises(PixivError):
        scan(remote)
    with context() as db:
        assert db.query(models.PixivFeedback).filter_by(pid="100", value="like").count() == 1
    remote.fail_private = False
    remote.unavailable = True
    scan(remote)
    with context() as db:
        assert db.query(models.PixivFeedback).filter_by(pid="100", value="like").count() == 1
    remote.unavailable = False
    scan(remote)
    with context() as db:
        assert db.query(models.PixivFeedback).filter_by(pid="100", value="like").count() == 0


def test_privacy_change_and_incremental_absence_never_remove(environment):
    context, _, _ = environment
    remote = Remote()
    enable(context)
    scan(remote)
    remote.public.clear()
    remote.private.add("100")
    scan(remote)
    remote.private.clear()
    scan(remote, full=False)
    with context() as db:
        row = db.query(models.PixivBookmarkState).filter_by(pid="100").one()
        assert row.desired is True and row.visibility == "private"
        assert row.missing_scans == 0


def test_remote_cancel_does_not_delete_cart_or_recreate_like(environment):
    context, _, _ = environment
    remote = Remote()
    enable(context)
    scan(remote)
    with context() as db:
        db.add(
            models.PixivCartItem(id="cart", account_revision="rev", actor_id=1, pid="100", pages=[0], metadata_json={})
        )
    remote.public.clear()
    scan(remote)
    scan(remote)
    with context() as db:
        account = db.get(models.PixivAccount, 1)
        bookmarks.intent(db, account, 1, "100", True, "auto_cart")
        assert bookmarks.state_for(db, account, "100").desired is False
        assert db.query(models.PixivCartItem).count() == 1
        assert db.query(models.PixivFeedback).filter_by(pid="100", value="like").count() == 0


def test_disabled_sync_is_local_and_admin_cannot_modify_bound_account(environment, monkeypatch):
    context, client, _ = environment
    remote = Remote()
    client.post("/api/pixiv-ol/feedback", json={"pid": "103", "value": "like"})
    monkeypatch.setattr(service, "client_for_job", lambda *args: remote)
    assert bookmarks.run_outbox_once() is False
    client.cookies.set("session_id", "session-2")
    assert client.post("/api/pixiv-ol/bookmarks/sync").status_code == 403
    assert client.post("/api/pixiv-ol/feedback", json={"pid": "104", "value": "like"}).status_code == 200
    with context() as db:
        assert db.query(models.PixivBookmarkState).filter_by(pid="104").count() == 0
    assert remote.calls == []


def test_lease_recovery_and_timeout_readback_avoid_duplicate_write(environment, monkeypatch):
    context, client, _ = environment
    remote = Remote()
    enable(context)
    scan(remote)
    client.post("/api/pixiv-ol/feedback", json={"pid": "103", "value": "like"})
    with context() as db:
        task = db.query(models.PixivBookmarkOutbox).one()
        task.status = "running"
        task.lease_until = datetime.utcnow() - timedelta(seconds=1)
    original = remote.call

    def timeout(method, **params):
        result = original(method, **params)
        if method == "illust_bookmark_add":
            raise PixivError("external_error")
        return result

    remote.call = timeout
    monkeypatch.setattr(service, "client_for_job", lambda *args: remote)
    assert bookmarks.run_outbox_once()
    with context() as db:
        db.query(models.PixivBookmarkOutbox).update({"available_at": datetime.utcnow()})
    assert bookmarks.run_outbox_once()
    assert len([m for m, _ in remote.calls if m == "illust_bookmark_add"]) == 1
    assert client.get("/api/pixiv-ol/bookmarks/states?pid=103").json()["items"][0]["sync"] == "synced"
