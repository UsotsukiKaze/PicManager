from contextlib import contextmanager
from datetime import datetime, timedelta
from pathlib import Path
from collections import Counter

import pytest
from fastapi.testclient import TestClient
from PIL import Image
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

import main
from app import models
from app.config import settings
from app.security import permissions
from app.integrations.pixiv_ol import jobs, service, provider
from app.integrations.pixiv_ol import cart, login, cli_login
from app.integrations.pixiv_ol.recommendations import TagIndex, inventory_quotas, rank_candidates
from app.routers.integrations import pixiv_ol as api


def artwork(pid="100", tags=None, pages=1):
    return {
        "id": int(pid),
        "title": "作品 <script>",
        "type": "illust",
        "user": {"id": 9, "name": "画师"},
        "create_date": datetime.utcnow().isoformat() + "Z",
        "x_restrict": 0,
        "page_count": pages,
        "tags": tags or [{"name": "游戏", "translated_name": None}],
        "image_urls": {"medium": "https://i.pximg.net/preview.jpg"},
        "meta_single_page": {"original_image_url": "https://i.pximg.net/100_p0.png"},
        "meta_pages": [{"image_urls": {"original": f"https://i.pximg.net/{pid}_p{x}.png"}} for x in range(pages)],
    }


@pytest.fixture
def environment(monkeypatch, tmp_path):
    engine = create_engine(
        f"sqlite:///{tmp_path / 'pixiv.db'}", connect_args={"check_same_thread": False, "timeout": 1}
    )
    models.Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)

    @contextmanager
    def context():
        with Session() as db:
            try:
                yield db
                db.commit()
            except Exception:
                db.rollback()
                raise

    for module in (main, service, jobs, api, permissions, cart, login, cli_login):
        monkeypatch.setattr(module, "get_db_context", context)
    for attr, value in {
        "BASE_DIR": str(tmp_path),
        "DATA_PATH": str(tmp_path / "data"),
        "STORE_PATH": str(tmp_path / "resource/store"),
        "TEMP_PATH": str(tmp_path / "resource/temp"),
        "STORAGE_BACKEND": "local",
        "PIXIV_OL_ENCRYPTION_KEY": "",
        "PIXIV_OL_REQUEST_INTERVAL": 0,
        "PIXIV_CLI_EXECUTABLE": "",
        "PIXIV_USE_SYSTEM_PROXY": False,
    }.items():
        monkeypatch.setattr(settings, attr, value)
    with context() as db:
        for user_id, role in ((1, "root"), (2, "admin"), (3, "user")):
            db.add(models.User(id=user_id, qq_number=settings.ROOT_QQ if role == "root" else str(user_id), role=role))
            db.add(
                models.UserSession(
                    session_id=f"session-{user_id}", user_id=user_id, expires_at=datetime.utcnow() + timedelta(hours=1)
                )
            )
        db.add(models.Group(id=1, name="游戏"))
        db.add(models.FeatureTag(id=1, name="白发", aliases=[models.FeatureTagAlias(alias="白髪")]))
        db.add(
            models.PixivAccount(
                id=1,
                user_id="7",
                name="Pixiv Root",
                owner_id=1,
                revision="rev",
                credential=provider.encrypt("test-token"),
                preferences={"groups": {"1": {"enabled": True}}},
                sync_state={},
            )
        )
    client = TestClient(main.app, base_url="http://localhost")
    client.headers["X-Pixiv-OL"] = "1"
    client.cookies.set("session_id", "session-1")
    yield context, client, tmp_path
    cli_login.shutdown()
    client.close()
    engine.dispose()


class FakeProvider:
    token = "rotated-token"
    user = {"id": "7", "name": "Pixiv Root"}
    cursor = staticmethod(provider.Provider.cursor)

    def __init__(self, token):
        self.raw = artwork()

    def call(self, method, **kwargs):
        return {"illust": self.raw} if method == "illust_detail" else {"illusts": [self.raw], "next_url": None}

    def close(self):
        pass


def install_fake(monkeypatch):
    monkeypatch.setattr(service, "Provider", FakeProvider)

    def download(url, path, **kwargs):
        Image.new("RGB", (32, 20), "blue").save(path, format="PNG")

    monkeypatch.setattr(jobs, "download", download)
    monkeypatch.setattr(api, "download", download)
    monkeypatch.setattr(cart, "download", download)


def test_permissions_csrf_and_private_cache(environment):
    _, client, _ = environment
    client.cookies.clear()
    assert client.get("/api/pixiv-ol/account").status_code == 401
    client.cookies.set("session_id", "session-3")
    assert client.get("/api/pixiv-ol/feed").status_code == 403
    assert client.get("/pixiv-ol").status_code == 403
    client.cookies.set("session_id", "session-2")
    assert client.get("/api/pixiv-ol/account").status_code == 200
    assert client.put("/api/pixiv-ol/preferences", json={}).status_code == 403
    assert client.post("/api/pixiv-ol/account/connect", json={"refresh_token": "secret"}).status_code == 403
    client.cookies.set("session_id", "session-1")
    assert client.post("/api/pixiv-ol/sync", json={}, headers={"Origin": "https://evil.example"}).status_code == 403
    client.headers.pop("X-Pixiv-OL")
    assert client.post("/api/pixiv-ol/sync", json={}).status_code == 403
    response = client.get("/api/pixiv-ol/account")
    assert response.headers["cache-control"] == "private, no-store"
    assert "credential" not in response.text and "test-token" not in response.text


def test_crypto_key_is_independent_persistent_and_authenticated(environment):
    _, _, tmp_path = environment
    encrypted = provider.encrypt("real-secret")
    assert encrypted != "real-secret"
    assert provider.decrypt(encrypted) == "real-secret"
    assert (tmp_path / "data/.pixiv_ol_key").is_file()
    with pytest.raises(provider.PixivError):
        provider.decrypt(encrypted[:-8] + "ABCDEFGH")


def test_matching_translation_alias_and_ambiguous_character(environment):
    context, _, _ = environment
    with context() as db:
        db.add(models.Group(id=2, name="其他作品"))
        db.add_all([models.Character(id=1, name="角色", group_id=1), models.Character(id=2, name="角色", group_id=2)])
    with context() as db:
        index = TagIndex(db)
        match = index.match([{"name": "游戏"}, {"name": "角色"}, {"name": "白髪"}])
        assert match["group_ids"] == [1]
        assert match["character_ids"] == [1]
        assert match["feature_tag_ids"] == [1]
        assert index.match([{"name": "角色"}])["conflicts"] == ["角色"]
        assert index.match([{"name": "white hair", "translated_name": "白发"}])["feature_tag_ids"] == [1]


def test_inventory_quotas_cap_zero_disable_and_alpha_zero():
    quotas = inventory_quotas({1: 5, 2: 25, 3: 100, 4: 0}, {})
    assert quotas[1] == pytest.approx(0.53023, abs=0.00001)
    assert 4 not in quotas
    equal = inventory_quotas({1: 5, 2: 100}, {"alpha": 0})
    assert equal == {1: 0.5, 2: 0.5}
    capped = inventory_quotas({1: 1, 2: 100000}, {})
    assert capped[1] / capped[2] <= 4.00001
    assert 1 not in inventory_quotas({1: 5, 2: 25}, {"groups": {"1": {"enabled": False}}})


def test_sync_resume_does_not_advance_success_on_partial(environment):
    context, _, _ = environment

    class Paginated(FakeProvider):
        def call(self, method, **kwargs):
            offset = int(kwargs.get("offset", 0))
            return {
                "illusts": [artwork(str(100 + offset))],
                "next_url": f"https://app-api.pixiv.net/v2/illust/follow?offset={offset+1}",
            }

    result = service.sync_feed(Paginated("token"), "rev", 1)
    assert result["partial"]
    with context() as db:
        state = db.get(models.PixivAccount, 1).sync_state["feed_public"]
        assert "last_success" not in state
        assert state["cursor"] == {"offset": "5"}
    result = service.sync_feed(FakeProvider("token"), "rev", 1)
    assert not result["partial"]
    with context() as db:
        assert db.get(models.PixivAccount, 1).sync_state["feed_public"]["last_success"]


@pytest.mark.parametrize("mode,initial_pages", [("native", 4), ("combined", 3)])
def test_browse_recommendations_resumes_upstream_and_preserves_old_batch(environment, mode, initial_pages):
    _, client, _ = environment

    class Pages(FakeProvider):
        offsets = []

        def call(self, method, **kwargs):
            if method != "illust_recommended":
                return super().call(method, **kwargs)
            offset = int(kwargs.get("offset", 0))
            self.offsets.append(offset)
            return {
                "illusts": [artwork(str(1000 + offset))],
                "next_url": f"https://app-api.pixiv.net/v1/illust/recommended?offset={offset+1}",
            }

    remote = Pages("test")
    first = service.refresh_candidates(remote, "rev", 1, mode)
    old = client.get(f"/api/pixiv-ol/recommendations?batch_id={first['batch_id']}&mode={mode}").json()
    second = service.refresh_candidates(remote, "rev", 1, mode, continuation=True)
    assert remote.offsets == list(range(initial_pages * 2))
    newer = client.get(f"/api/pixiv-ol/recommendations?batch_id={second['batch_id']}&mode={mode}").json()
    assert str(1000 + initial_pages) in {item["pid"] for item in newer["items"]}
    assert first["more"] and second["more"]
    assert client.get(f"/api/pixiv-ol/recommendations?batch_id={first['batch_id']}&mode={mode}").json() == old


def test_following_history_continues_past_sync_cutoff_without_latest_sync_rewinding(environment):
    context, client, _ = environment

    class History(FakeProvider):
        offsets = []

        def call(self, method, **kwargs):
            offset = int(kwargs.get("offset", 0))
            self.offsets.append(offset)
            raw = artwork(str(1000 + offset))
            raw["create_date"] = (datetime.utcnow() - timedelta(days=10 + offset)).isoformat()
            return {"illusts": [raw], "next_url": f"https://app-api.pixiv.net/v2/illust/follow?offset={offset+1}"}

    remote = History("test")
    assert not service.sync_feed(remote, "rev", 1)["partial"]
    first = client.get("/api/pixiv-ol/feed").json()
    assert first["next_cursor"] is None and first["tail_cursor"]
    assert service.continue_feed(remote, "rev", 1)["more"]
    assert remote.offsets == [0, 1, 2]
    older = client.get("/api/pixiv-ol/feed", params={"cursor": first["tail_cursor"]}).json()
    assert {item["pid"] for item in older["items"]} == {"1001", "1002"}
    service.sync_feed(remote, "rev", 1)
    with context() as db:
        assert db.get(models.PixivAccount, 1).sync_state["feed_public"]["history_cursor"] == {"offset": "3"}
    service.continue_feed(remote, "rev", 1)
    assert remote.offsets[-2:] == [3, 4]


def test_browse_job_deduplicates_and_stops_only_when_upstream_exhausted(environment, monkeypatch):
    context, client, _ = environment
    install_fake(monkeypatch)
    first = client.post("/api/pixiv-ol/browse", json={"view": "recommendations", "mode": "native"})
    second = client.post("/api/pixiv-ol/browse", json={"view": "recommendations", "mode": "native"})
    assert first.status_code == 202 and first.json()["id"] == second.json()["id"]
    assert jobs.Worker().run_once()
    with context() as db:
        job = db.get(models.PixivJob, first.json()["id"])
        assert job.status == "completed" and job.result["batch_id"]
        assert job.result["more"] is False
    remote = FakeProvider("test")
    monkeypatch.setattr(remote, "call", lambda *a, **k: pytest.fail("exhausted stream must not restart at page 1"))
    assert service.refresh_candidates(remote, "rev", 1, "native", continuation=True) == {"count": 0, "more": False}
    client.cookies.set("session_id", "session-3")
    assert client.post("/api/pixiv-ol/browse", json={"view": "feed"}).status_code == 403


def test_browse_error_keeps_continuation_cursor_for_retry(environment):
    context, _, _ = environment
    with context() as db:
        db.get(models.PixivAccount, 1).sync_state = {
            "recommendation_stream_native": {"cursor": {"offset": "120"}, "exhausted": False}
        }

    class Offline(FakeProvider):
        def call(self, method, **kwargs):
            assert kwargs["offset"] == "120"
            raise provider.PixivError("rate_limited")

    with pytest.raises(provider.PixivError, match="rate_limited"):
        service.refresh_candidates(Offline("test"), "rev", 1, "native", continuation=True)
    with context() as db:
        assert db.get(models.PixivAccount, 1).sync_state["recommendation_stream_native"]["cursor"] == {"offset": "120"}


def test_import_idempotency_tags_sources_and_derived_jobs(environment, monkeypatch):
    context, client, tmp_path = environment
    install_fake(monkeypatch)
    payload = {
        "pid": "100",
        "pages": [0],
        "group_ids": [1],
        "feature_tag_ids": [1],
        "new_tags": ["白髪", "制服"],
        "idempotency_key": "request_100",
    }
    first = client.post("/api/pixiv-ol/imports", json=payload)
    assert first.status_code == 202
    assert client.post("/api/pixiv-ol/imports", json=payload).json()["id"] == first.json()["id"]
    assert jobs.Worker().run_once()
    with context() as db:
        assert db.query(models.Image).count() == 1
        image = db.query(models.Image).one()
        assert {x.name for x in image.feature_tags} == {"白发", "制服", "Pixiv"}
        assert db.query(models.PixivImageSource).one().page_index == 0
        assert db.query(models.ImageJob).count() == 2
        assert db.get(models.PixivJob, first.json()["id"]).status == "completed"
        assert Path(tmp_path / image.file_path).is_file()
    payload["idempotency_key"] = "new_request_100"
    client.post("/api/pixiv-ol/imports", json=payload)
    assert jobs.Worker().run_once()
    with context() as db:
        assert db.query(models.Image).count() == 1


def test_publish_database_failure_rolls_back_and_compensates(environment, monkeypatch):
    context, client, tmp_path = environment
    install_fake(monkeypatch)

    def fail(*args, **kwargs):
        raise RuntimeError("injected db failure")

    monkeypatch.setattr(jobs, "add_source", fail)
    client.post(
        "/api/pixiv-ol/imports",
        json={"pid": "100", "pages": [0], "group_ids": [1], "new_tags": ["新标签"], "idempotency_key": "failed_import"},
    )
    assert jobs.Worker().run_once()
    with context() as db:
        assert db.query(models.Image).count() == 0
        assert db.query(models.PixivImageSource).count() == 0
        assert db.query(models.FeatureTag).filter_by(name="新标签").count() == 0
        assert db.query(models.ImageJob).count() == 0
        assert db.query(models.PixivJob).one().status == "retry"
    assert not list((tmp_path / "resource/store").glob("*"))


def test_download_does_not_hold_database_writer(environment, monkeypatch):
    context, client, _ = environment
    install_fake(monkeypatch)
    original = jobs.download

    def write_while_downloading(url, path, **kwargs):
        with context() as db:
            db.get(models.User, 2).nickname = "write during download"
        original(url, path, **kwargs)

    monkeypatch.setattr(jobs, "download", write_while_downloading)
    client.post(
        "/api/pixiv-ol/imports",
        json={"pid": "100", "pages": [0], "group_ids": [1], "idempotency_key": "short_transactions"},
    )
    jobs.Worker().run_once()
    with context() as db:
        assert db.query(models.PixivJob).one().status == "completed"
        assert db.get(models.User, 2).nickname == "write during download"


def test_duplicate_without_character_waits_for_decision(environment, monkeypatch):
    context, client, _ = environment
    install_fake(monkeypatch)
    with context() as db:
        db.add(
            models.Image(
                image_id="AAAAAAAAAA",
                file_extension="png",
                file_path="existing.png",
                perceptual_hash="0000000000000000",
                groups=[db.get(models.Group, 1)],
            )
        )
    response = client.post(
        "/api/pixiv-ol/imports",
        json={"pid": "100", "pages": [0], "group_ids": [1], "idempotency_key": "duplicate_import"},
    )
    worker = jobs.Worker()
    worker.run_once()
    with context() as db:
        assert db.get(models.PixivJob, response.json()["id"]).status == "awaiting_duplicate"
    assert (
        client.post(f"/api/pixiv-ol/imports/{response.json()['id']}/resolve", json={"action": "different"}).status_code
        == 202
    )
    worker.run_once()
    with context() as db:
        assert db.query(models.Image).count() == 2


def test_revoke_permission_and_change_account_cancel_old_jobs(environment, monkeypatch):
    context, client, _ = environment
    install_fake(monkeypatch)
    client.post("/api/pixiv-ol/sync", json={})
    with context() as db:
        db.get(models.User, 1).role = "user"
    jobs.Worker().run_once()
    with context() as db:
        assert db.query(models.PixivJob).one().error == "permission_revoked"


def test_preview_requires_admin_and_is_never_public(environment, monkeypatch):
    context, client, _ = environment
    install_fake(monkeypatch)
    service.save_artworks("rev", [artwork()], "recommended", 1)
    response = client.get("/api/pixiv-ol/previews/100")
    assert response.status_code == 200
    assert response.headers["content-type"] == "image/webp"
    assert response.headers["cache-control"] == "private, no-store"
    client.cookies.clear()
    assert client.get("/api/pixiv-ol/previews/100").status_code == 401


def test_supply_sufficient_small_groups_receive_more_slots(environment):
    context, _, _ = environment
    with context() as db:
        for group_id, size in ((1, 5), (2, 25), (3, 100)):
            group = db.get(models.Group, group_id)
            if not group:
                group = models.Group(id=group_id, name=f"作品{group_id}")
                db.add(group)
            for number in range(size):
                db.add(
                    models.Image(
                        image_id=f"{group_id}{number:09}", file_extension="png", file_path="fixture.png", groups=[group]
                    )
                )
            for number in range(50):
                raw = artwork(str(group_id * 1000 + number), tags=[{"name": group.name}])
                art = service.normalize_artwork(raw)
                db.add(
                    models.PixivArtwork(
                        account_revision="rev",
                        pid=art["pid"],
                        author_id=str(number),
                        title=art["title"],
                        published_at=service.iso_date(art["published_at"]),
                        metadata_json=art,
                        origins=[],
                    )
                )
        db.get(models.PixivAccount, 1).preferences = {}
    with context() as db:
        items, profile = rank_candidates(db, db.get(models.PixivAccount, 1))
        counts = Counter(x["primary_group"] for x in items[:20])
        assert counts[1] > counts[2] > counts[3]
        assert profile["inventory"] == {1: 5, 2: 25, 3: 100}


def test_provider_rejects_untrusted_redirects_and_cursor():
    assert not provider.trusted_image_url("https://i.pximg.net.evil.test/image.png")
    assert not provider.trusted_image_url("https://user:pass@i.pximg.net/image.png")
    assert not provider.trusted_image_url("https://i.pximg.net:8443/image.png")
    assert provider.Provider.cursor("https://app-api.pixiv.net/v2/illust/follow?offset=30") == {"offset": "30"}
    with pytest.raises(provider.PixivError):
        provider.Provider.cursor("https://evil.test/?offset=30")


def test_new_library_pid_infers_pixiv_page_without_touching_other_sources(environment):
    context, _, _ = environment
    with context() as db:
        for number, pid, filename in ((1, "123", "123_p4.png"), (2, None, "456_p2.jpg"), (3, "X:123", "123_p0.png")):
            db.add(
                models.Image(
                    image_id=str(number).zfill(10),
                    pid=pid,
                    original_filename=filename,
                    file_extension="png",
                    file_path="fixture",
                )
            )
    with context() as db:
        assert [db.get(models.Image, str(number).zfill(10)).pid for number in (1, 2, 3)] == [
            "123_p4",
            "456_p2",
            "X:123",
        ]


def test_artist_is_shared_and_removed_only_after_last_image_or_identity_change(environment):
    from app.pixiv_metadata import apply_metadata

    context, _, _ = environment
    art = service.normalize_artwork(artwork(pages=2))
    with context() as db:
        images = [models.Image(image_id=str(n).zfill(10), file_extension="png", file_path="fixture") for n in (1, 2)]
        db.add_all(images)
        for page, image in enumerate(images):
            apply_metadata(db, image, art, page)
    with context() as db:
        assert db.query(models.PixivArtist).count() == 1
        assert db.get(models.Image, "0000000001").pid == "100_p0"
        db.delete(db.get(models.Image, "0000000001"))
    with context() as db:
        assert db.query(models.PixivArtist).count() == 1
        db.get(models.Image, "0000000002").pid = "999_p1"
    with context() as db:
        assert db.query(models.PixivArtist).count() == 0
        assert db.query(models.PixivImageMetadata).count() == 0


def test_likes_survive_cached_batches_feed_and_reload_and_can_be_cleared(environment, monkeypatch):
    context, client, _ = environment
    install_fake(monkeypatch)
    service.save_artworks("rev", [artwork()], "feed_public", 1)
    for mode in ("native", "combined"):
        client.post("/api/pixiv-ol/sync", json={"kind": "recommendations", "mode": mode})
        assert jobs.worker.run_once()
    assert client.post("/api/pixiv-ol/feedback", json={"pid": "100", "value": "like"}).status_code == 200
    endpoints = ("/feed", "/recommendations?mode=native", "/recommendations?mode=combined")
    for endpoint in endpoints:
        assert client.get("/api/pixiv-ol" + endpoint).json()["items"][0]["liked"] is True
    assert client.get("/api/pixiv-ol/artworks/100").json()["liked"] is True
    client.cookies.set("session_id", "session-2")
    assert client.get("/api/pixiv-ol/feed").json()["items"][0]["liked"] is False
    client.cookies.set("session_id", "session-1")
    client.post("/api/pixiv-ol/feedback", json={"pid": "100", "value": "clear"})
    for endpoint in endpoints:
        assert client.get("/api/pixiv-ol" + endpoint).json()["items"][0]["liked"] is False


def test_original_reader_fetches_each_page_preserves_pixels_and_requires_admin(environment, monkeypatch):
    import io
    from app.integrations.pixiv_ol import viewer

    _, client, _ = environment
    service.save_artworks("rev", [artwork(pages=2)], "recommended", 1)
    calls = []

    def download(url, path, **kwargs):
        calls.append(url)
        Image.new("RGB", (1200, 900), "blue" if "p1" in url else "red").save(path, format="PNG")

    monkeypatch.setattr(viewer, "download", download)
    for page, color in ((0, (255, 0, 0)), (1, (0, 0, 255)), (1, (0, 0, 255))):
        response = client.get(f"/api/pixiv-ol/artworks/100/original?page={page}")
        assert response.status_code == 200
        assert response.headers["content-type"] == "image/png"
        assert response.headers["cache-control"] == "private, no-store"
        with Image.open(io.BytesIO(response.content)) as image:
            assert image.size == (1200, 900) and image.getpixel((1, 1)) == color
    assert len(calls) == 2
    client.cookies.clear()
    assert client.get("/api/pixiv-ol/artworks/100/original").status_code == 401


def test_automatic_group_quotas_ignore_stale_manual_priority():
    counts = {1: 5, 2: 25, 3: 100}
    prefs = {"groups": {"1": {"priority": 0}, "3": {"priority": 10}}}
    assert inventory_quotas(counts, prefs) == inventory_quotas(counts, {})


def test_reader_preview_uses_clear_master_per_page_not_original_and_caches(environment, monkeypatch):
    from app.integrations.pixiv_ol import viewer

    _, client, _ = environment
    raw = artwork(pages=2)
    for page, entry in enumerate(raw["meta_pages"]):
        entry["image_urls"][
            "large"
        ] = f"https://i.pximg.net/c/600x1200_90_webp/img-master/img/2026/100_p{page}_master1200.jpg"
    raw["user"]["profile_image_urls"] = {"medium": "https://i.pximg.net/user-profile/img/9.jpg"}
    service.save_artworks("rev", [raw], "recommended", 1)
    calls = []

    def fetch(url, path, **kwargs):
        calls.append((url, kwargs["limit"]))
        Image.new("RGB", (800, 1200), "blue").save(path, format="JPEG")

    monkeypatch.setattr(viewer, "download", fetch)
    item = client.get("/api/pixiv-ol/artworks/100").json()
    assert "author_avatar" not in item and "page_previews" not in item
    assert item["author_avatar_url"].endswith("/avatar")
    for page in (0, 1, 1):
        response = client.get(item["reader_preview_url"] + f"?page={page}")
        assert response.status_code == 200
        assert response.headers["cache-control"] == "private, no-store"
    assert calls == [
        (f"https://i.pximg.net/img-master/img/2026/100_p{page}_master1200.jpg", 8 * 1024 * 1024) for page in (0, 1)
    ]
    assert client.get(item["author_avatar_url"]).status_code == 200
    assert calls[-1][1] == 2 * 1024 * 1024
    client.cookies.clear()
    assert client.get(item["reader_preview_url"]).status_code == 401
    assert client.get(item["author_avatar_url"]).status_code == 401


def test_clear_preview_upgrades_legacy_original_url_and_rejects_unknown_original():
    from app.integrations.pixiv_ol import viewer

    art = {
        "pid": "100",
        "page_count": 2,
        "originals": [
            "https://i.pximg.net/img-original/img/2026/100_p0.png",
            "https://i.pximg.net/img-original/img/2026/100_p1.jpg",
        ],
    }
    assert viewer.clear_preview_url(art, 1) == "https://i.pximg.net/img-master/img/2026/100_p1_master1200.jpg"
    with pytest.raises(provider.PixivError):
        viewer.clear_preview_url(art, 2)
    art["originals"][1] = "https://i.pximg.net/unknown-original.png"
    with pytest.raises(provider.PixivError):
        viewer.clear_preview_url(art, 1)


def test_avatar_lazily_refreshes_old_summary_once_without_exposing_cdn_url(environment, monkeypatch):
    from app.integrations.pixiv_ol import viewer

    context, client, _ = environment
    service.save_artworks("rev", [artwork()], "recommended", 1)
    with context() as db:
        row = db.query(models.PixivArtwork).one()
        row.metadata_json = {k: v for k, v in row.metadata_json.items() if k != "author_avatar"}
    remote_calls = []

    class ArtistProvider(FakeProvider):
        def call(self, method, **kwargs):
            remote_calls.append(method)
            raw = artwork()
            raw["user"]["profile_image_urls"] = {"medium": "https://i.pximg.net/user-profile/img/9.jpg"}
            return {"illust": raw}

    monkeypatch.setattr(service, "Provider", ArtistProvider)
    monkeypatch.setattr(
        viewer, "download", lambda url, path, **kwargs: Image.new("RGB", (100, 100)).save(path, format="PNG")
    )
    assert client.get("/api/pixiv-ol/artworks/100/avatar").status_code == 200
    assert client.get("/api/pixiv-ol/artworks/100/avatar").status_code == 200
    assert remote_calls == ["illust_detail"]
    assert "i.pximg.net" not in client.get("/api/pixiv-ol/artworks/100").text


def test_cart_reader_preview_rechecks_selected_pages_and_owner(environment, monkeypatch):
    from app.integrations.pixiv_ol import viewer

    _, client, _ = environment
    install_fake(monkeypatch)
    service.save_artworks("rev", [artwork(pages=2)], "recommended", 1)
    item = client.post("/api/pixiv-ol/cart", json={"pid": "100", "pages": [1]}).json()
    monkeypatch.setattr(viewer, "clear_preview", lambda *args: (Path(settings.TEMP_PATH) / "test.jpg", "image/jpeg"))
    Path(settings.TEMP_PATH).mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (100, 100)).save(Path(settings.TEMP_PATH) / "test.jpg")
    url = item["artwork"]["reader_preview_url"]
    assert client.get(url + "?page=1").status_code == 200
    assert client.get(url + "?page=0").status_code == 404
    client.cookies.set("session_id", "session-2")
    assert client.get(url + "?page=1").status_code == 404


def test_viewer_parallel_files_and_same_file_coalesce(environment, monkeypatch):
    import threading
    from concurrent.futures import ThreadPoolExecutor
    from app.integrations.pixiv_ol import viewer

    barrier = threading.Barrier(2)
    calls = []

    def fetch(url, path, **kwargs):
        calls.append(url)
        barrier.wait(timeout=3)
        Image.new("RGB", (100, 100)).save(path, format="PNG")

    monkeypatch.setattr(viewer, "download", fetch)
    with ThreadPoolExecutor(max_workers=2) as pool:
        tasks = [
            pool.submit(viewer.cached_media, f"https://i.pximg.net/{n}.png", "rev", f"parallel-{n}", 1024**2)
            for n in (1, 2)
        ]
        assert all(task.result(timeout=5)[0].exists() for task in tasks)
    assert len(calls) == 2
    entered, release = threading.Event(), threading.Event()

    def shared_fetch(url, path, **kwargs):
        calls.append(url)
        entered.set()
        assert release.wait(timeout=3)
        Image.new("RGB", (100, 100)).save(path, format="PNG")

    monkeypatch.setattr(viewer, "download", shared_fetch)
    with ThreadPoolExecutor(max_workers=4) as pool:
        tasks = [
            pool.submit(viewer.cached_media, "https://i.pximg.net/same.png", "rev", "shared", 1024**2) for _ in range(4)
        ]
        assert entered.wait(timeout=3)
        release.set()
        assert len({task.result(timeout=5)[0] for task in tasks}) == 1
    assert calls.count("https://i.pximg.net/same.png") == 1
    assert not viewer.FILE_LOCKS


def test_reader_webp_preserves_dimensions_and_migrates_cached_jpeg_without_redownload(environment, monkeypatch):
    from app.integrations.pixiv_ol import viewer

    art = service.normalize_artwork(artwork())
    path = Path(settings.TEMP_PATH) / "pixiv-ol-viewer/rev/100_p0-preview.img"
    path.parent.mkdir(parents=True)
    Image.new("RGB", (822, 1200), "blue").save(path, format="JPEG")
    old_size = path.stat().st_size
    monkeypatch.setattr(
        viewer, "download", lambda *args, **kwargs: pytest.fail("Cached preview must not download again")
    )
    result, kind = viewer.clear_preview(art, "rev", 0)
    assert result == path and kind == "image/webp" and path.stat().st_size < old_size
    with Image.open(path) as image:
        assert image.size == (822, 1200)


def test_account_avatar_cached_profile_private_response(environment, monkeypatch):
    from app.integrations.pixiv_ol import viewer

    context, client, _ = environment
    calls = []

    class AccountProvider(FakeProvider):
        def call(self, method, **kwargs):
            calls.append(method)
            return {"user": {"id": 7, "profile_image_urls": {"medium": "https://i.pximg.net/user-profile/7.jpg"}}}

    monkeypatch.setattr(service, "Provider", AccountProvider)
    monkeypatch.setattr(
        viewer, "download", lambda url, path, **kwargs: Image.new("RGB", (100, 100)).save(path, format="PNG")
    )
    account = client.get("/api/pixiv-ol/account").json()
    assert account["avatar_url"] == "/api/pixiv-ol/account/avatar"
    assert client.get(account["avatar_url"]).status_code == 200
    assert client.get(account["avatar_url"]).status_code == 200
    assert calls == ["user_detail"]
    with context() as db:
        assert db.get(models.PixivAccount, 1).sync_state["account_profile"]["avatar"]
    assert "i.pximg.net" not in client.get("/api/pixiv-ol/account").text
    client.cookies.clear()
    assert client.get(account["avatar_url"]).status_code == 401


def test_feed_cursor_keeps_older_scroll_stable_when_new_post_arrives(environment):
    _, client, _ = environment
    start = datetime.utcnow()
    raws = []
    for index in range(55):
        raw = artwork(str(1000 + index))
        raw["create_date"] = (start - timedelta(minutes=index)).isoformat()
        raws.append(raw)
    service.save_artworks("rev", raws, "feed_public", 1)
    first = client.get("/api/pixiv-ol/feed?limit=24").json()
    assert len(first["items"]) == 24 and first["next_cursor"]
    newest = artwork("9999")
    newest["create_date"] = (start + timedelta(minutes=1)).isoformat()
    service.save_artworks("rev", [newest], "feed_public", 1)
    second = client.get("/api/pixiv-ol/feed", params={"limit": 24, "cursor": first["next_cursor"]}).json()
    third = client.get("/api/pixiv-ol/feed", params={"limit": 24, "cursor": second["next_cursor"]}).json()
    pids = [item["pid"] for batch in (first, second, third) for item in batch["items"]]
    assert len(pids) == len(set(pids)) == 55 and "9999" not in pids
    assert third["next_cursor"] is None
    assert client.get("/api/pixiv-ol/feed", params={"cursor": "invalid"}).status_code == 422


def test_old_work_reuses_another_work_artist_avatar_without_remote_auth(environment, monkeypatch):
    from app.integrations.pixiv_ol import viewer

    context, client, _ = environment
    first, second = artwork("100"), artwork("101")
    first["user"]["profile_image_urls"] = {"medium": "https://i.pximg.net/user-profile/9.jpg"}
    service.save_artworks("rev", [first, second], "recommended", 1)
    with context() as db:
        row = db.query(models.PixivArtwork).filter_by(pid="101").one()
        row.metadata_json = {k: v for k, v in row.metadata_json.items() if k != "author_avatar"}
    monkeypatch.setattr(service, "client_for_job", lambda *args: pytest.fail("Artist avatar already known"))
    monkeypatch.setattr(
        viewer, "download", lambda url, path, **kwargs: Image.new("RGB", (100, 100)).save(path, format="PNG")
    )
    assert client.get("/api/pixiv-ol/artworks/101/avatar").status_code == 200
    with context() as db:
        assert db.query(models.PixivArtwork).filter_by(pid="101").one().metadata_json["author_avatar"]


def test_pixiv_library_check_preserves_old_image_and_queues_only_selected_missing_pages(environment, monkeypatch):
    from app import pixiv_check

    context, client, tmp_path = environment
    monkeypatch.setattr(pixiv_check, "get_db_context", context)
    install_fake(monkeypatch)

    def init(self, token):
        self.raw = artwork(pages=3)

    monkeypatch.setattr(FakeProvider, "__init__", init)
    path = tmp_path / "old.png"
    Image.new("RGB", (32, 20), "red").save(path)
    with context() as db:
        db.add(
            models.Image(
                image_id="0000000001",
                pid="100_p1",
                file_extension="png",
                file_path=str(path),
                groups=[db.get(models.Group, 1)],
            )
        )
    before = path.read_bytes()
    review = pixiv_check.scan_next(1)
    assert review["suggested_page"] == 1 and review["artwork"]["page_count"] == 3
    result = pixiv_check.resolve(review["review_id"], 1, 1, [1, 2])
    assert result["pages"] == [2] and result["import_job_id"]
    assert path.read_bytes() == before
    with context() as db:
        image = db.get(models.Image, "0000000001")
        assert image.pid == "100_p1" and image.pixiv_metadata.artist.name == "画师"
        assert "Pixiv" in {tag.name for tag in image.feature_tags}
    assert jobs.worker.run_once()
    with context() as db:
        assert db.get(models.PixivJob, result["import_job_id"]).status == "completed"
        assert {image.pid for image in db.query(models.Image).all()} == {"100_p1", "100_p2"}
        assert db.query(models.PixivArtist).count() == 1
    with pytest.raises(provider.PixivError, match="check_review_expired"):
        pixiv_check.resolve(review["review_id"], 1, 1, [0])


def test_pixiv_check_rejects_stale_file_or_other_actor_without_metadata_mutation(environment, monkeypatch):
    from app import pixiv_check

    context, _, tmp_path = environment
    monkeypatch.setattr(pixiv_check, "get_db_context", context)
    install_fake(monkeypatch)
    monkeypatch.setattr(FakeProvider, "__init__", lambda self, token: setattr(self, "raw", artwork(pages=2)))
    path = tmp_path / "old.png"
    Image.new("RGB", (32, 20), "red").save(path)
    with context() as db:
        db.add(models.Image(image_id="0000000001", pid="100", file_extension="png", file_path=str(path)))
    review = pixiv_check.scan_next(1)
    with pytest.raises(provider.PixivError, match="check_review_expired"):
        pixiv_check.resolve(review["review_id"], 2, 0, [])
    path.write_bytes(path.read_bytes() + b"changed")
    with pytest.raises(provider.PixivError, match="image_changed"):
        pixiv_check.resolve(review["review_id"], 1, 0, [])
    with context() as db:
        assert db.query(models.PixivImageMetadata).count() == 0


def test_unavailable_pixiv_work_does_not_block_scan_or_invent_artist_and_tags(environment, monkeypatch):
    from app import pixiv_check
    from app.pixiv_metadata import public_metadata

    context, _, tmp_path = environment
    monkeypatch.setattr(pixiv_check, "get_db_context", context)
    install_fake(monkeypatch)

    def gone(self, method, **kwargs):
        raise provider.PixivError("artwork_unavailable")

    monkeypatch.setattr(FakeProvider, "call", gone)
    path = tmp_path / "old.png"
    Image.new("RGB", (32, 20), "red").save(path)
    with context() as db:
        db.add(models.Image(image_id="0000000001", pid="100", file_extension="png", file_path=str(path)))
    assert pixiv_check.scan_next(1)["status"] == "unavailable"
    assert pixiv_check.scan_next(1)["status"] == "complete"
    with context() as db:
        image = db.get(models.Image, "0000000001")
        assert image.pixiv_metadata.status == "unavailable"
        assert public_metadata(image)["pixiv_verified"] is False
        assert db.query(models.PixivArtist).count() == 0 and not image.feature_tags


def test_single_page_validation_fills_metadata_without_a_review_or_original_replacement(environment, monkeypatch):
    from app import pixiv_check

    context, _, tmp_path = environment
    monkeypatch.setattr(pixiv_check, "get_db_context", context)
    install_fake(monkeypatch)
    path = tmp_path / "old.png"
    Image.new("RGB", (32, 20), "red").save(path)
    before = path.read_bytes()
    with context() as db:
        db.add(models.Image(image_id="0000000001", pid="100", file_extension="png", file_path=str(path)))
    result = pixiv_check.scan_next(1)
    assert result["status"] == "validated" and result["pid"] == "100_p0"
    assert path.read_bytes() == before
    with context() as db:
        image = db.get(models.Image, "0000000001")
        assert image.pixiv_metadata.artist.name == "画师"
        assert "Pixiv" in {tag.name for tag in image.feature_tags}
        assert db.query(models.PixivCheckReview).count() == 0


def test_cart_original_is_page_specific_and_private_to_owner(environment, monkeypatch):
    _, client, _ = environment
    install_fake(monkeypatch)

    def init(self, token):
        self.raw = artwork(pages=2)

    monkeypatch.setattr(FakeProvider, "__init__", init)
    service.save_artworks("rev", [artwork(pages=2)], "recommended", 1)
    item = client.post("/api/pixiv-ol/cart", json={"pid": "100", "pages": [1]}).json()
    assert jobs.worker.run_once()
    path = f"/api/pixiv-ol/cart/{item['id']}/original"
    assert client.get(path + "?page=1").status_code == 200
    assert client.get(path + "?page=0").status_code == 404
    client.cookies.set("session_id", "session-2")
    assert client.get(path + "?page=1").status_code == 404


def test_library_artist_search_and_image_metadata_serialization(environment):
    from app.pixiv_metadata import apply_metadata
    from app.services import ImageService
    from app.schemas import ImageSearchParams

    context, _, tmp_path = environment
    path = tmp_path / "artist.png"
    Image.new("RGB", (32, 20), "red").save(path)
    with context() as db:
        image = models.Image(image_id="0000000001", file_extension="png", file_path=str(path))
        db.add(image)
        apply_metadata(db, image, service.normalize_artwork(artwork()), 0)
    with context() as db:
        for artist in ("9", "画师"):
            images, total = ImageService.search_images(db, ImageSearchParams(artist=artist))
            assert total == 1 and images[0]["artist"]["name"] == "画师"
            assert images[0]["pid"] == "100_p0" and images[0]["pixiv_tags"]
        assert ImageService.search_images(db, ImageSearchParams(artist="unknown"))[1] == 0


@pytest.mark.parametrize("kind", ["recommendations", "sync"])
def test_real_pixivpy_jsondict_flows_through_worker_and_cached_feed(environment, monkeypatch, kind):
    import json
    from types import SimpleNamespace

    context, client, _ = environment
    parsed = provider.AppPixivAPI.parse_json(json.dumps({"illusts": [artwork()]}))
    assert hasattr(parsed, "model_dump") and not callable(parsed.model_dump)
    assert provider.plain(parsed) is parsed

    def transport(self, method, url, *args, **kwargs):
        payload = (
            {
                "access_token": "synthetic-access-token",
                "refresh_token": "synthetic-refresh-token-12345",
                "user": {"id": 7, "name": "Synthetic"},
            }
            if method == "POST"
            else {"illusts": [artwork()], "next_url": None}
        )
        return SimpleNamespace(status_code=200, headers={}, text=json.dumps(payload), json=lambda: payload)

    monkeypatch.setattr(provider.AppPixivAPI, "requests_call", transport)
    job = client.post("/api/pixiv-ol/sync", json={"kind": kind, "mode": "native"}).json()
    assert jobs.worker.run_once()
    with context() as db:
        row = db.get(models.PixivJob, job["id"])
        assert row.status == "completed", row.error
        assert db.get(models.PixivAccount, 1).status == "connected"
    endpoint = "/recommendations?mode=native" if kind == "recommendations" else "/feed"
    response = client.get("/api/pixiv-ol" + endpoint)
    assert response.status_code == 200
    assert response.json()["total"] == 1


@pytest.mark.parametrize("wrapped", [True, False])
def test_real_pixivpy_refresh_accepts_both_envelopes_and_persists_rotated_token(environment, monkeypatch, wrapped):
    from types import SimpleNamespace
    import json

    context, _, _ = environment
    payload = {
        "access_token": "synthetic-access-token-1234567890",
        "refresh_token": "synthetic-rotated-token-1234567890",
        "user": {"id": 7, "name": "Synthetic"},
    }
    remote = {"response": payload} if wrapped else payload
    received = []

    def transport(self, method, url, **kwargs):
        received.append(kwargs)
        return SimpleNamespace(status_code=200, headers={}, text=json.dumps(remote), json=lambda: remote)

    monkeypatch.setattr(provider.AppPixivAPI, "requests_call", transport)
    with context() as db:
        db.get(models.PixivAccount, 1).status = "reauth_required"
    instance = service.client_for_job(1, "rev")
    try:
        assert instance.user["id"] == "7"
        assert instance.api.access_token == payload["access_token"]
        assert instance.api.user_id == 7
    finally:
        instance.close()
    with context() as db:
        account = db.get(models.PixivAccount, 1)
        assert account.status == "connected"
        assert provider.decrypt(account.credential) == payload["refresh_token"]
    assert received[0]["data"]["grant_type"] == "refresh_token"
    assert received[0]["data"]["include_policy"] == "true"


@pytest.mark.parametrize(
    "failure,expected,disconnected",
    [
        ("network", "login_network_error", False),
        ("malformed", "login_response_invalid", False),
        ("upstream", "external_error", False),
        ("client", "login_client_rejected", False),
        ("unknown400", "external_error", False),
        ("grant", "reauth_required", True),
        ("unauthorized", "reauth_required", True),
    ],
)
def test_refresh_failures_only_disconnect_for_confirmed_invalid_credentials(
    environment, monkeypatch, failure, expected, disconnected
):
    from types import SimpleNamespace

    context, client, _ = environment

    def transport(*args, **kwargs):
        if failure == "network":
            raise RuntimeError("private-network-description")
        status, body = {
            "malformed": (200, {"unexpected": "private-remote-value"}),
            "upstream": (503, {}),
            "client": (400, {"error": "invalid_client"}),
            "unknown400": (400, {"error": "invalid_request"}),
            "grant": (400, {"error": "invalid_grant"}),
            "unauthorized": (401, {}),
        }[failure]
        return SimpleNamespace(status_code=status, headers={}, json=lambda: body)

    monkeypatch.setattr(provider.AppPixivAPI, "requests_call", transport)
    job = client.post("/api/pixiv-ol/sync", json={"kind": "recommendations"}).json()
    assert jobs.worker.run_once()
    with context() as db:
        account = db.get(models.PixivAccount, 1)
        row = db.get(models.PixivJob, job["id"])
        assert row.error == expected
        assert row.status == ("failed" if disconnected else "retry")
        assert account.status == ("reauth_required" if disconnected else "connected")
        assert provider.decrypt(account.credential) == "test-token"


def test_reconnect_invalidates_old_account_candidates_and_jobs(environment, monkeypatch):
    context, client, _ = environment
    install_fake(monkeypatch)
    monkeypatch.setattr(FakeProvider, "user", {"id": "8", "name": "Other Pixiv"})
    service.save_artworks("rev", [artwork()], "recommended", 1)
    assert client.post("/api/pixiv-ol/sync", json={}).status_code == 202
    response = client.post("/api/pixiv-ol/account/connect", json={"refresh_token": "a" * 30})
    assert response.status_code == 200
    with context() as db:
        account = db.get(models.PixivAccount, 1)
        assert account.revision != "rev"
        assert provider.decrypt(account.credential) == "rotated-token"
        assert db.query(models.PixivArtwork).count() == 0
        assert db.query(models.PixivJob).one().status == "cancelled"


def test_recommendation_batch_reflects_imported_pages_without_reordering(environment):
    context, client, _ = environment
    with context() as db:
        art = service.normalize_artwork(artwork(pages=2))
        db.add(
            models.PixivRecommendationBatch(
                id="batch", account_revision="rev", mode="combined", items=[art], profile={}
            )
        )
        image = models.Image(image_id="1234567890", file_extension="png", file_path="fixture.png")
        db.add(image)
        db.flush()
        db.add(
            models.PixivImageSource(
                image_id=image.image_id, provider="pixiv", work_id="100", page_index=1, sha256="hash", metadata_json={}
            )
        )
    response = client.get("/api/pixiv-ol/recommendations?batch_id=batch")
    assert response.status_code == 200
    result = response.json()
    assert result["batch_id"] == "batch" and result["total"] == 1
    assert result["items"][0]["imported_pages"] == [1]
    assert "originals" not in result["items"][0]


def test_existing_library_pids_are_shared_by_cached_recommendations_feed_and_detail(environment):
    context, client, _ = environment
    service.save_artworks('rev', [artwork(pages=3)], 'feed_public', 1)
    with context() as db:
        db.add(models.Image(image_id='1234567890', pid='100', file_extension='png', file_path='legacy.png'))
        db.add(models.Image(image_id='1234567891', pid='100_p2', file_extension='png', file_path='page2.png'))
        db.flush()
        db.execute(models.Image.__table__.update().where(models.Image.image_id=='1234567890').values(pid='100'))
        db.add(models.PixivRecommendationBatch(id='legacy', account_revision='rev', mode='combined', items=[service.normalize_artwork(artwork(pages=3))], profile={}))
    paths=['/api/pixiv-ol/recommendations?batch_id=legacy', '/api/pixiv-ol/feed', '/api/pixiv-ol/artworks/100']
    for path in paths:
        response=client.get(path)
        assert response.status_code == 200
        body=response.json()
        item=body['items'][0] if 'items' in body else body
        assert item['imported_pages'] == [0,2]
    added=client.post('/api/pixiv-ol/cart', json={'pid':'100','pages':[0,1,2]})
    assert added.status_code == 202
    assert added.json()['pages'] == [1]
    with context() as db:
        db.add(models.Image(image_id='1234567892', pid='100_p1', file_extension='png', file_path='page1.png'))
    assert client.get('/api/pixiv-ol/recommendations?batch_id=legacy').json()['items'][0]['imported_pages'] == [0,1,2]
    with context() as db:
        assert rank_candidates(db, db.get(models.PixivAccount,1))[0] == []


def test_library_pid_lookup_handles_legacy_filenames_and_rejects_false_prefixes(environment):
    from app.pixiv_metadata import library_pixiv_pages
    context, client, _ = environment
    with context() as db:
        rows=[{'image_id':f'{offset:010d}','pid':pid,'original_filename':filename,'file_extension':'png','file_path':'fixture.png'} for offset,(pid,filename) in enumerate([('100',None),('100_p02',None),('100','100_p1.jpg'),('100_p1000',None),('1000_p0',None),('１００_p0',None),('100x_p0',None)])]
        db.execute(models.Image.__table__.insert(),rows)
        db.add(models.Image(image_id='9999999999',file_extension='png',file_path='metadata.png'))
        db.flush()
        db.add(models.PixivImageMetadata(image_id='9999999999',work_id='100',page_index=3,page_count=4,tags=[]))
        db.add(models.PixivImageSource(image_id='9999999999',provider='other',work_id='100',page_index=4,sha256='hash',metadata_json={}))
    with context() as db:
        assert library_pixiv_pages(db,['100']) == {'100':{0,1,2,3}}
        assert library_pixiv_pages(db,[]) == {}
    result=client.get('/api/pixiv-ol/library-status?pid=100&pid=1000&pid=200')
    assert result.status_code == 200
    assert result.json()['items'] == [{'pid':'100','imported_pages':[0,1,2,3]},{'pid':'1000','imported_pages':[0]},{'pid':'200','imported_pages':[]}]
    assert client.get('/api/pixiv-ol/library-status?pid=100_p0').status_code == 422
    assert client.get('/api/pixiv-ol/library-status',params=[('pid',str(n)) for n in range(101)]).status_code == 422
    client.cookies.clear()
    assert client.get('/api/pixiv-ol/library-status?pid=100').status_code == 401


def test_fully_imported_legacy_pid_cannot_be_added_and_import_reuses_existing_image(environment, monkeypatch):
    context, client, _ = environment
    install_fake(monkeypatch)
    service.save_artworks('rev',[artwork()],'recommended',1)
    with context() as db:
        db.add(models.Image(image_id='1234567890',pid='100',file_extension='png',file_path='legacy.png'))
        db.flush()
        db.execute(models.Image.__table__.update().where(models.Image.image_id=='1234567890').values(pid='100'))
    assert client.post('/api/pixiv-ol/cart',json={'pid':'100'}).status_code == 409
    def no_download(*args,**kwargs):
        raise AssertionError('Existing library PID must not be redownloaded')
    monkeypatch.setattr(jobs,'download',no_download)
    response=client.post('/api/pixiv-ol/imports',json={'pid':'100','pages':[0],'group_ids':[1],'idempotency_key':'legacy_existing'})
    assert response.status_code == 202
    assert jobs.Worker().run_once()
    with context() as db:
        job=db.get(models.PixivJob,response.json()['id'])
        assert job.status == 'completed'
        assert job.result['done'] == [{'page':0,'image_id':'1234567890','existing':True}]
        assert db.query(models.Image).count() == 1


def test_candidate_refresh_persists_mixed_and_native_batches(environment, monkeypatch):
    context, client, _ = environment
    install_fake(monkeypatch)
    provider_client = FakeProvider("test")
    for mode in ("combined", "native"):
        result = service.refresh_candidates(provider_client, "rev", 1, mode)
        assert result["warnings"] == []
        assert result["count"] == 1
        response = client.get(f"/api/pixiv-ol/recommendations?mode={mode}&batch_id={result['batch_id']}")
        assert response.status_code == 200
        assert response.json()["items"][0]["pid"] == "100"
    with context() as db:
        assert db.query(models.PixivRecommendationBatch).count() == 2


def stage_cart(client, monkeypatch, pid="100"):
    install_fake(monkeypatch)

    class MatchingProvider(FakeProvider):
        def call(self, method, **kwargs):
            return (
                {"illust": artwork(str(kwargs["illust_id"]))}
                if method == "illust_detail"
                else super().call(method, **kwargs)
            )

    monkeypatch.setattr(service, "Provider", MatchingProvider)
    service.save_artworks("rev", [artwork(pid)], "recommended", 1)
    response = client.post("/api/pixiv-ol/cart", json={"pid": pid})
    assert response.status_code == 202
    item = response.json()
    assert jobs.Worker().run_once()
    return item["id"]


def test_cart_caches_temp_then_imports_without_pixiv_or_redownload(environment, monkeypatch):
    context, client, _ = environment
    id_ = stage_cart(client, monkeypatch)
    assert (cart.directory(id_) / "0.img").is_file()
    assert client.post("/api/pixiv-ol/cart", json={"pid": "100"}).json()["id"] == id_
    row = client.get("/api/pixiv-ol/cart").json()["items"][0]
    assert row["status"] == "ready" and row["cached_pages"] == [0]
    assert client.get(row["preview_url"]).status_code == 200

    def no_network(*args, **kwargs):
        raise AssertionError("Cached import must not contact Pixiv")

    monkeypatch.setattr(service, "client_for_job", no_network)
    monkeypatch.setattr(jobs, "download", no_network)
    response = client.post("/api/pixiv-ol/cart/imports", json={"item_ids": [id_]})
    assert response.status_code == 202
    assert jobs.Worker().run_once()
    assert client.get("/api/pixiv-ol/cart").json()["items"] == []
    assert not cart.directory(id_).exists()
    with context() as db:
        assert db.query(models.Image).count() == 1
        assert db.query(models.PixivImageSource).one().work_id == "100"
        assert db.query(models.PixivJob).filter_by(kind="import").one().status == "completed"


def test_split_cart_confirms_each_page_and_imports_independent_tags_offline(environment, monkeypatch):
    context, client, _ = environment
    install_fake(monkeypatch)
    raw = artwork(pages=2, tags=[{"name": "游戏"}, {"name": "另一作品"}, {"name": "角色一"}, {"name": "角色二"}])
    service.save_artworks("rev", [raw], "recommended", 1)
    with context() as db:
        db.add(models.Group(id=2, name="另一作品"))
        db.add_all([models.Character(id=11, name="角色一", group_id=1), models.Character(id=22, name="角色二", group_id=2)])
        db.get(models.PixivAccount, 1).preferences = {"groups": {"1": {"enabled": True}, "2": {"enabled": True}}}

    class MultiProvider(FakeProvider):
        def call(self, method, **kwargs):
            return {"illust": raw}

    monkeypatch.setattr(service, "Provider", MultiProvider)

    def download_page(url, path, **kwargs):
        Image.new("RGB", (32, 20), "red" if "_p0" in url else "blue").save(path, format="PNG")

    monkeypatch.setattr(cart, "download", download_page)
    added = client.post("/api/pixiv-ol/cart", json={"pid": "100", "pages": [0, 1], "import_mode": "split"})
    assert added.status_code == 202
    row = added.json()
    id_ = row["id"]
    assert row["draft"]["confirmed_pages"] == []
    assert set(row["draft"]["page_drafts"]) == {"0", "1"}
    assert jobs.Worker().run_once()
    blocked = client.post("/api/pixiv-ol/cart/imports", json={"item_ids": [id_]})
    assert blocked.status_code == 409 and blocked.json()["detail"] == "pages_unconfirmed"
    assert client.put(f"/api/pixiv-ol/cart/{id_}", json={"pages": [0, 1], "group_ids": [1]}).status_code == 409
    assert client.put(f"/api/pixiv-ol/cart/{id_}/pages/9", json={"group_ids": [1]}).status_code == 422
    assert client.put(f"/api/pixiv-ol/cart/{id_}/pages/0", json={"group_ids": [999]}).status_code == 409
    first = client.put(f"/api/pixiv-ol/cart/{id_}/pages/0", json={"group_ids": [1], "character_ids": [11]})
    assert first.status_code == 200 and first.json()["draft"]["confirmed_pages"] == [0]
    assert client.post("/api/pixiv-ol/cart/imports", json={"item_ids": [id_]}).status_code == 409
    second = client.put(f"/api/pixiv-ol/cart/{id_}/pages/1", json={"group_ids": [2], "character_ids": [22], "feature_tag_ids": [1], "age_rating": "r16"})
    assert second.status_code == 200
    assert second.json()["draft"]["page_drafts"]["0"]["character_ids"] == [11]
    repeated = client.post("/api/pixiv-ol/cart", json={"pid": "100", "import_mode": "merged"}).json()
    assert repeated["id"] == id_ and repeated["draft"]["import_mode"] == "split"
    assert repeated["draft"]["confirmed_pages"] == [0, 1]
    preview0 = client.get(f"/api/pixiv-ol/cart/{id_}/preview?page=0")
    preview1 = client.get(f"/api/pixiv-ol/cart/{id_}/preview?page=1")
    assert preview0.status_code == preview1.status_code == 200
    assert preview0.content != preview1.content
    assert preview0.headers["cache-control"] == "private, no-store"
    assert client.get(f"/api/pixiv-ol/cart/{id_}/preview?page=2").status_code == 404
    client.cookies.set("session_id", "session-2")
    assert client.get(f"/api/pixiv-ol/cart/{id_}/preview?page=1").status_code != 200
    assert client.put(f"/api/pixiv-ol/cart/{id_}/pages/0", json={"group_ids": [1]}).status_code != 200
    client.cookies.set("session_id", "session-1")

    def no_network(*args, **kwargs):
        raise AssertionError("Import must use cached originals")

    monkeypatch.setattr(service, "client_for_job", no_network)
    monkeypatch.setattr(jobs, "download", no_network)
    assert client.post("/api/pixiv-ol/cart/imports", json={"item_ids": [id_]}).status_code == 202
    assert client.put(f"/api/pixiv-ol/cart/{id_}/pages/0", json={"group_ids": [1]}).status_code == 409
    assert jobs.Worker().run_once()
    with context() as db:
        images = {image.pid: image for image in db.query(models.Image).all()}
        assert set(images) == {"100_p0", "100_p1"}
        assert [c.id for c in images["100_p0"].characters] == [11]
        assert [c.id for c in images["100_p1"].characters] == [22]
        assert [g.id for g in images["100_p0"].groups] == [1]
        assert [g.id for g in images["100_p1"].groups] == [2]
        assert {t.name for t in images["100_p0"].feature_tags} == {"Pixiv"}
        assert {t.name for t in images["100_p1"].feature_tags} == {"Pixiv", "白发"}
        assert images["100_p0"].age_rating == "all" and images["100_p1"].age_rating == "r16"
        assert db.query(models.PixivCartItem).count() == 0


def test_split_job_never_falls_back_to_shared_tags_when_a_page_draft_is_missing(environment):
    context, _, _ = environment
    draft = {"actor_id": 1, "pages": [0, 1], "import_mode": "split", "group_ids": [1], "confirmed_pages": [0, 1], "page_drafts": {"0": {"group_ids": [1]}}}
    with context() as db, pytest.raises(provider.PixivError, match="invalid_page_draft"):
        jobs.validate_import_draft(db, draft)


def test_cart_is_private_to_actor_and_remove_cleans_temp(environment, monkeypatch):
    _, client, _ = environment
    id_ = stage_cart(client, monkeypatch)
    client.cookies.set("session_id", "session-2")
    assert client.get("/api/pixiv-ol/cart").json()["total"] == 0
    assert client.get(f"/api/pixiv-ol/cart/{id_}/preview").status_code != 200
    assert client.delete(f"/api/pixiv-ol/cart/{id_}").status_code != 200
    client.cookies.set("session_id", "session-1")
    assert client.delete(f"/api/pixiv-ol/cart/{id_}").status_code == 200
    assert not cart.directory(id_).exists()


def test_cart_add_persists_auto_like_and_removal_preserves_it_until_user_clears(environment):
    context, client, _ = environment
    service.save_artworks("rev", [artwork()], "feed_public", 1)
    added = client.post("/api/pixiv-ol/cart", json={"pid": "100"}).json()
    assert added["artwork"]["liked"] is True
    repeated = client.post("/api/pixiv-ol/cart", json={"pid": "100"}).json()
    assert repeated["id"] == added["id"] and repeated["artwork"]["liked"] is True
    assert client.get("/api/pixiv-ol/cart").json()["items"][0]["artwork"]["liked"] is True
    assert client.get("/api/pixiv-ol/artworks/100").json()["liked"] is True
    with context() as db:
        assert db.query(models.PixivFeedback).count() == 1
    client.cookies.set("session_id", "session-2")
    assert client.get("/api/pixiv-ol/artworks/100").json()["liked"] is False
    client.cookies.set("session_id", "session-1")
    removed = client.delete(f"/api/pixiv-ol/cart/{added['id']}").json()
    assert removed == {"removed": True, "pid": "100", "liked": True}
    assert client.get("/api/pixiv-ol/cart").json()["items"] == []
    assert client.get("/api/pixiv-ol/artworks/100").json()["liked"] is True
    client.post("/api/pixiv-ol/feedback", json={"pid": "100", "value": "clear"})
    assert client.get("/api/pixiv-ol/artworks/100").json()["liked"] is False


def test_rejected_cart_add_does_not_add_like(environment):
    context, client, _ = environment
    service.save_artworks("rev", [artwork()], "feed_public", 1)
    assert client.post("/api/pixiv-ol/cart", json={"pid": "100", "pages": [10]}).status_code == 409
    with context() as db:
        assert db.query(models.PixivCartItem).count() == db.query(models.PixivFeedback).count() == 0


def test_cart_batch_validates_all_drafts_before_queuing(environment, monkeypatch):
    context, client, _ = environment
    one = stage_cart(client, monkeypatch)
    two = stage_cart(client, monkeypatch, "101")
    assert client.put(f"/api/pixiv-ol/cart/{two}", json={"pages": [0]}).status_code == 200
    assert client.post("/api/pixiv-ol/cart/imports", json={"item_ids": [one, two]}).status_code == 409
    with context() as db:
        assert db.query(models.PixivJob).filter_by(kind="import").count() == 0


def test_cart_rejects_tampered_cache(environment, monkeypatch):
    _, client, _ = environment
    id_ = stage_cart(client, monkeypatch)
    (cart.directory(id_) / "0.img").write_bytes(b"tampered")
    response = client.post("/api/pixiv-ol/cart/imports", json={"item_ids": [id_]})
    assert response.status_code == 409 and response.json()["detail"] == "cache_changed"


def test_oauth_pkce_official_url_encrypted_verifier_and_single_use(environment, monkeypatch):
    context, client, _ = environment
    install_fake(monkeypatch)
    result = client.post("/api/pixiv-ol/account/login", json={"mode": "manual"})
    assert result.status_code == 200
    session = result.json()
    assert session["url"].startswith(login.LOGIN_URL + "?") and "code_challenge_method=S256" in session["url"]
    with context() as db:
        row = db.get(models.PixivLoginSession, session["id"])
        verifier = provider.decrypt(row.verifier)
        assert verifier not in result.text and row.verifier != verifier
    exchanges = []

    def exchange(code, saved_verifier):
        assert code == "one-use-code" and saved_verifier == verifier
        exchanges.append(code)
        return "a" * 30

    monkeypatch.setattr(login, "exchange", exchange)
    path = f"/api/pixiv-ol/account/login/{session['id']}/complete"
    assert client.post(path, json={"code": "pixiv://account/login?code=one-use-code"}).status_code == 200
    assert client.post(path, json={"code": "one-use-code"}).status_code == 409
    assert exchanges == ["one-use-code"]
    assert client.get(f"/api/pixiv-ol/account/login/{session['id']}").json()["status"] == "completed"


def test_oauth_expiry_permissions_and_callback_origin(environment, monkeypatch):
    context, client, _ = environment
    session = client.post("/api/pixiv-ol/account/login", json={"mode": "manual"}).json()
    path = f"/api/pixiv-ol/account/login/{session['id']}/complete"
    assert client.post(path, json={"code": "https://evil.test/?code=hello"}).status_code == 422
    assert (
        client.post(
            path, json={"code": login.LOGIN_URL.replace("/login", "/users/auth/pixiv/start") + "?code_challenge=test"}
        ).status_code
        == 422
    )
    with context() as db:
        db.get(models.PixivLoginSession, session["id"]).expires_at = datetime.utcnow() - timedelta(seconds=1)
    assert client.post(path, json={"code": "code"}).status_code == 409
    client.cookies.set("session_id", "session-2")
    assert client.post("/api/pixiv-ol/account/login", json={"mode": "manual"}).status_code == 403


def test_default_browser_login_keeps_manual_session_and_reopen_verifier(environment, monkeypatch):
    context, client, _ = environment
    opened = []
    monkeypatch.setattr(login, "local_request", lambda request: True)
    monkeypatch.setattr(login, "open_default_browser", lambda url: opened.append(url) or True)
    monkeypatch.setattr(login, "browser_executable", lambda: pytest.fail("Default login must not use Playwright"))
    response = client.post("/api/pixiv-ol/account/login", json={})
    assert response.status_code == 200
    session = response.json()
    assert session["opened"] and not session["automatic"]
    with context() as db:
        row = db.get(models.PixivLoginSession, session["id"])
        assert row.status == "waiting"
        verifier = row.verifier
    recovered = client.get("/api/pixiv-ol/account/login/pending").json()["session"]
    assert recovered["id"] == session["id"] and recovered["url"] == session["url"]
    reopened = client.post(f"/api/pixiv-ol/account/login/{session['id']}/open")
    assert reopened.status_code == 200 and reopened.json()["opened"]
    assert opened == [session["url"], session["url"]]
    with context() as db:
        assert db.get(models.PixivLoginSession, session["id"]).verifier == verifier
        assert db.query(models.PixivLoginSession).count() == 1


def test_default_browser_login_never_opens_server_browser_for_remote_request(environment, monkeypatch):
    _, client, _ = environment
    monkeypatch.setattr(login, "local_request", lambda request: False)
    monkeypatch.setattr(login, "open_default_browser", lambda _: pytest.fail("Remote request opened server browser"))
    session = client.post("/api/pixiv-ol/account/login", json={}).json()
    assert not session["opened"] and not session["automatic"]
    assert not client.post(f"/api/pixiv-ol/account/login/{session['id']}/open").json()["opened"]
    client.delete(f"/api/pixiv-ol/account/login/{session['id']}")
    assert client.get("/api/pixiv-ol/account/login/pending").json()["session"] is None


def test_default_browser_reopen_rejects_expired_and_non_root_access(environment):
    context, client, _ = environment
    session = client.post("/api/pixiv-ol/account/login", json={"mode": "manual"}).json()
    with context() as db:
        db.get(models.PixivLoginSession, session["id"]).expires_at = datetime.utcnow() - timedelta(seconds=1)
    assert client.get("/api/pixiv-ol/account/login/pending").json()["session"] is None
    assert client.post(f"/api/pixiv-ol/account/login/{session['id']}/open").status_code == 409
    client.cookies.set("session_id", "session-2")
    assert client.get("/api/pixiv-ol/account/login/pending").status_code == 403
    assert client.post(f"/api/pixiv-ol/account/login/{session['id']}/open").status_code == 403


def test_default_browser_opener_uses_os_url_association_and_restricts_destination(monkeypatch):
    opened = []
    monkeypatch.setattr(login.sys, "platform", "win32")
    monkeypatch.setattr(login.os, "startfile", opened.append, raising=False)
    assert login.open_default_browser(login.login_url("a" * 48))
    assert len(opened) == 1
    for url in (
        "file:///C:/Windows/test.exe",
        "https://evil.test/",
        "https://app-api.pixiv.net@evil.test/web/v1/login",
    ):
        assert not login.open_default_browser(url)
    assert len(opened) == 1

    def unavailable(_):
        raise OSError("No default browser")

    monkeypatch.setattr(login.os, "startfile", unavailable)
    assert not login.open_default_browser(login.login_url("a" * 48))


@pytest.mark.parametrize(
    "status,payload,expected",
    [
        (400, {"error": "invalid_grant"}, "login_exchange_failed"),
        (400, {"error": "invalid_request"}, "login_authorization_rejected"),
        (400, {"error": "invalid_request", "errors": {"system": {"code": 918}}}, "login_authorization_rejected"),
        (401, {"error": "invalid_client"}, "login_client_rejected"),
        (400, {"error": "unauthorized_client"}, "login_client_rejected"),
        (503, {"error": "server_error"}, "login_service_unavailable"),
        (302, {}, "login_authorization_rejected"),
        (403, {}, "access_denied"),
        (429, {}, "rate_limited"),
    ],
)
def test_oauth_exchange_rejections_are_specific_and_do_not_leak_remote_body(
    environment, monkeypatch, status, payload, expected
):
    from types import SimpleNamespace

    context, client, _ = environment
    logs = []
    monkeypatch.setattr(provider, "log_error", logs.append)
    monkeypatch.setattr(login, "log_error", logs.append)
    remote = {**payload, "error_description": "private-remote-message", "refresh_token": "private-remote-token"}
    response = SimpleNamespace(status_code=status, headers={}, json=lambda: remote)
    monkeypatch.setattr(provider.AppPixivAPI, "requests_call", lambda *args, **kwargs: response)
    session = client.post("/api/pixiv-ol/account/login", json={"mode": "manual"}).json()
    result = client.post(f"/api/pixiv-ol/account/login/{session['id']}/complete", json={"code": "private-code"})
    assert result.status_code == 409 and result.json()["detail"] == expected
    with context() as db:
        row = db.get(models.PixivLoginSession, session["id"])
        assert row.status == "failed" and row.error == expected and row.verifier == ""
    assert any("stage=exchange" in item for item in logs)
    assert not any(
        secret in " ".join(logs) + result.text
        for secret in ("private-remote-message", "private-remote-token", "private-code")
    )


def test_oauth_exchange_headers_network_and_invalid_response(environment, monkeypatch):
    import hashlib
    from types import SimpleNamespace

    received = []

    def transport(self, method, url, **kwargs):
        received.append(kwargs)
        return SimpleNamespace(status_code=200, json=lambda: {"refresh_token": "t" * 30})

    monkeypatch.setattr(provider.AppPixivAPI, "requests_call", transport)
    assert login.exchange("local-code", "local-verifier") == "t" * 30
    headers, data = received[0]["headers"], received[0]["data"]
    stamp = headers["X-Client-Time"]
    assert headers["X-Client-Hash"] == hashlib.md5((stamp + provider.BoundedAPI.hash_secret).encode()).hexdigest()
    assert data["code"] == "local-code" and data["code_verifier"] == "local-verifier"
    assert data["redirect_uri"] == login.REDIRECT_URI

    def broken(*args, **kwargs):
        raise RuntimeError("private-network-message")

    monkeypatch.setattr(provider.AppPixivAPI, "requests_call", broken)
    with pytest.raises(provider.PixivError, match="^login_network_error$"):
        login.exchange("local-code", "local-verifier")

    for invalid in ([], {"response": []}, {"refresh_token": "short"}):
        monkeypatch.setattr(
            provider.AppPixivAPI,
            "requests_call",
            lambda *args, **kwargs: SimpleNamespace(status_code=200, json=lambda: invalid),
        )
        with pytest.raises(provider.PixivError, match="^login_response_invalid$"):
            login.exchange("local-code", "local-verifier")


def test_oauth_connect_failure_logs_the_following_stage(environment, monkeypatch):
    _, client, _ = environment
    logs = []
    monkeypatch.setattr(login, "log_error", logs.append)
    monkeypatch.setattr(login, "exchange", lambda *args: "private-refresh-token")

    def connect(*args):
        raise provider.PixivError("reauth_required")

    monkeypatch.setattr(service, "connect", connect)
    session = client.post("/api/pixiv-ol/account/login", json={"mode": "manual"}).json()
    result = client.post(f"/api/pixiv-ol/account/login/{session['id']}/complete", json={"code": "private-code"})
    assert result.json()["detail"] == "reauth_required"
    assert any("stage=connect" in item for item in logs)
    assert "private-refresh-token" not in " ".join(logs) and "private-code" not in " ".join(logs)


@pytest.mark.parametrize("value", [
    "https://app-api.pixiv.net/web/v1/users/auth/pixiv/callback?state=test&code=synthetic-code",
    "https//app-api.pixiv.net/web/v1/users/auth/pixiv/callback?state=test&code=synthetic-code",
    "app-api.pixiv.net/web/v1/users/auth/pixiv/callback?code=synthetic-code",
    '“https//app-api.pixiv.net/web/v1/users/auth/pixiv/callback?code=synthetic-code”',
    "pixiv://account/login?code=synthetic-code",
    "synthetic-code",
])
def test_remote_manual_authorization_input_reaches_exchange(environment, monkeypatch, value):
    context, client, _ = environment
    monkeypatch.setattr(login, "local_request", lambda _: False)
    install_fake(monkeypatch)
    exchanges = []
    monkeypatch.setattr(login, "exchange", lambda code, verifier: exchanges.append(code) or "a" * 30)
    session = client.post("/api/pixiv-ol/account/login", json={}).json()
    assert not session["opened"] and not session["automatic"]
    response = client.post(f"/api/pixiv-ol/account/login/{session['id']}/complete", json={"code": value})
    assert response.status_code == 200
    assert exchanges == ["synthetic-code"]
    with context() as db:
        assert db.get(models.PixivLoginSession, session["id"]).status == "completed"


@pytest.mark.parametrize("value", [
    "https//app-api.pixiv.net/web/v1/users/auth/pixiv/start?code=synthetic",
    "https//app-api.pixiv.net@evil.test/web/v1/users/auth/pixiv/callback?code=synthetic",
    "https://app-api.pixiv.net:8443/web/v1/users/auth/pixiv/callback?code=synthetic",
    "https//app-api.pixiv.net/web/v1/users/auth/pixiv/callback?code=one&code=two",
    "https//app-api.pixiv.net/web/v1/users/auth/pixiv/callback?code=&code=one",
    "https//app-api.pixiv.net/web/v1/users/auth/pixiv/callback?code=one#fragment",
    "https//app-api.pixiv.net/web/v1/users/auth/pixiv/callback?code=%22",
    "https//app-api.pixiv.net/web/v1/users/auth/pixiv/callback?code=one\nextra text",
    "code=synthetic",
])
def test_invalid_pasted_authorization_does_not_consume_session(environment, monkeypatch, value):
    context, client, _ = environment
    monkeypatch.setattr(login, "exchange", lambda *_: pytest.fail("Invalid callback reached exchange"))
    session = client.post("/api/pixiv-ol/account/login", json={"mode": "manual"}).json()
    response = client.post(f"/api/pixiv-ol/account/login/{session['id']}/complete", json={"code": value})
    assert response.status_code == 422
    with context() as db:
        row = db.get(models.PixivLoginSession, session["id"])
        assert row.status == "waiting" and row.verifier


def test_callback_parser_rejects_ambiguous_destinations_and_uses_rfc_pkce_vector():
    from urllib.parse import parse_qs, urlparse

    verifier = "dBjftJeZ4CVP-mB92K27uhbUJU1p1r_wW1gFWFOEjXk"
    params = parse_qs(urlparse(login.login_url(verifier)).query)
    assert params["code_challenge"] == ["E9Melhoa2OwvFrEMTJguCHaoeK1t8URWbuGJSstw-cM"]
    for value in (
        "https://name@ app-api.pixiv.net/web/v1/users/auth/pixiv/callback?code=a",
        "https://name@app-api.pixiv.net/web/v1/users/auth/pixiv/callback?code=a",
        "https://app-api.pixiv.net:8443/web/v1/users/auth/pixiv/callback?code=a",
        "https://app-api.pixiv.net:web/web/v1/users/auth/pixiv/callback?code=a",
        "https://app-api.pixiv.net/web/v1/users/auth/pixiv/callback?code=a&code=b",
        "https://app-api.pixiv.net/web/v1/users/auth/pixiv/callback?code=a#secret",
        "pixiv://account/login?code=a&code=b",
    ):
        assert login.callback_code(value) is None
    assert login.callback_code(login.REDIRECT_URI + "?state=s&code=a&via=login") == "a"
    assert login.callback_code("pixiv://account/login?code=a") == "a"


@pytest.mark.parametrize("source", ["callback_request", "redirect_header", "custom_navigation", "window_closed"])
def test_browser_keeps_captured_code_when_navigation_aborts(environment, source):
    from types import SimpleNamespace
    from playwright.sync_api import Error as BrowserError

    context, client, _ = environment
    session = client.post("/api/pixiv-ol/account/login", json={"mode": "manual"}).json()
    with context() as db:
        db.get(models.PixivLoginSession, session["id"]).status = "browser"

    class BrowserContext:
        def __init__(self):
            self.events, self.cdp_events = {}, {}
            self.pages = []
            self.aborted = False

        def on(self, name, handler):
            self.events[name] = handler

        def route(self, pattern, handler):
            self.route_handler = handler

        def new_cdp_session(self, page):
            return SimpleNamespace(
                send=lambda *_: None, on=lambda name, handler: self.cdp_events.update({name: handler})
            )

        def new_page(self):
            self.pages = [SimpleNamespace(goto=self.goto, wait_for_timeout=self.wait, on=lambda *_: None)]
            self.events["page"](self.pages[0])
            return self.pages[0]

        def capture(self):
            if source == "callback_request":

                def abort():
                    self.aborted = True

                self.route_handler(
                    SimpleNamespace(request=SimpleNamespace(url=login.REDIRECT_URI + "?code=good-code"), abort=abort)
                )
            elif source == "redirect_header":
                self.events["response"](
                    SimpleNamespace(
                        url="https://app-api.pixiv.net/web/v1/users/auth/pixiv/start",
                        status=302,
                        headers={"location": login.REDIRECT_URI + "?code=good-code"},
                    )
                )
            else:
                self.cdp_events["Page.frameRequestedNavigation"]({"url": "pixiv://account/login?code=good-code"})

        def goto(self, *_args, **_kwargs):
            if source != "window_closed":
                self.capture()
                raise BrowserError("net::ERR_ABORTED")

        def wait(self, _):
            self.capture()
            self.pages = []
            raise BrowserError("Target closed")

    browser = BrowserContext()
    assert login.capture_browser_code(browser, session["id"], 1, session["url"]) == "good-code"
    if source == "callback_request":
        assert browser.aborted


def test_browser_failure_logs_do_not_include_authorization_data(environment, monkeypatch):
    import playwright.sync_api
    from playwright.sync_api import Error as BrowserError

    context, client, _ = environment
    session = client.post("/api/pixiv-ol/account/login", json={"mode": "manual"}).json()
    with context() as db:
        db.get(models.PixivLoginSession, session["id"]).status = "browser"
    logs = []
    monkeypatch.setattr(login, "log_error", logs.append)

    def unavailable():
        raise BrowserError("failed URL: callback?code=private-authorization-code")

    monkeypatch.setattr(playwright.sync_api, "sync_playwright", unavailable)
    login.browser_login(session["id"], 1, session["url"])
    assert logs and "stage=open" in logs[0]
    assert "private-authorization-code" not in logs[0] and "callback?" not in logs[0]
    with context() as db:
        row = db.get(models.PixivLoginSession, session["id"])
        assert row.status == "failed" and not row.verifier


def test_same_account_reauthentication_preserves_cart_and_preferences(environment, monkeypatch):
    context, client, _ = environment
    id_ = stage_cart(client, monkeypatch)
    response = client.post("/api/pixiv-ol/account/connect", json={"refresh_token": "a" * 30})
    assert response.status_code == 200
    with context() as db:
        assert db.get(models.PixivAccount, 1).revision == "rev"
        assert db.get(models.PixivAccount, 1).preferences["groups"]["1"]["enabled"]
        assert db.get(models.PixivCartItem, id_) is not None
    assert (cart.directory(id_) / "0.img").is_file()


def test_restart_recovers_interrupted_cart_cache(environment, monkeypatch):
    context, client, _ = environment
    id_ = stage_cart(client, monkeypatch)
    (cart.directory(id_) / "0.img").unlink()
    with context() as db:
        item = db.get(models.PixivCartItem, id_)
        item.status = "caching"
        job = db.get(models.PixivJob, item.cache_job_id)
        job.status, job.locked_at = "running", datetime.utcnow()

    class NoThread:
        def __init__(self, **kwargs):
            pass

        def start(self):
            pass

        def is_alive(self):
            return False

    monkeypatch.setattr(jobs.threading, "Thread", NoThread)
    worker = jobs.Worker()
    worker.start()
    assert worker.run_once()
    assert (cart.directory(id_) / "0.img").is_file()
    assert client.get("/api/pixiv-ol/cart").json()["items"][0]["status"] == "ready"


def test_cart_orphan_cleanup_keeps_live_cache_and_unowned_directories(environment, monkeypatch):
    _, client, _ = environment
    id_ = stage_cart(client, monkeypatch)
    orphan = cart.directory("b" * 32)
    orphan.mkdir()
    (orphan / "old.img").write_bytes(b"old")
    unowned = orphan.parent / "other-data"
    unowned.mkdir()
    cart.cleanup_orphans()
    assert not orphan.exists()
    assert (cart.directory(id_) / "0.img").is_file()
    assert unowned.is_dir()

def test_exact_mapping_is_scoped_selected_and_preserves_manual(environment):
    from app.tag_mappings import exact_mappings, save_mapping
    context, _, _ = environment
    with context() as db:
        db.add_all([models.Group(id=2,name='未选分组'),models.Character(id=10,name='角色',group_id=1),models.Character(id=11,name='角色',group_id=2)])
        db.flush()
        prefs={'groups':{'1':{'enabled':True},'2':{'enabled':False}}}
        assert exact_mappings(db,[{'name':'游戏'},{'name':'角色'},{'name':'未选分组'}],prefs)==2
        character=db.query(models.PixivTagMapping).filter_by(target_type='character').one()
        assert (character.target_id,character.group_context,character.character_id,character.source)==(10,1,10,'exact')
        assert exact_mappings(db,[{'name':'游戏'},{'name':'角色'}],prefs)==0
        save_mapping(db,'角色','ignore',None,1)
        assert exact_mappings(db,[{'name':'角色'}],prefs)==0
        assert db.query(models.PixivTagMapping).filter_by(group_context=1).one().target_type=='ignore'
        db.delete(db.get(models.Group,1));db.flush()
        assert db.query(models.PixivTagMapping).count()==0


def test_global_manual_mapping_cannot_be_overridden_by_exact_character(environment):
    from app.tag_mappings import exact_mappings, save_mapping
    context, _, _ = environment
    with context() as db:
        db.add(models.Character(id=10,name='角色',group_id=1));db.flush()
        save_mapping(db,'角色','ignore',None)
        assert exact_mappings(db,[{'name':'角色'}],{'groups':{'1':{'enabled':True}}})==0
        assert db.query(models.PixivTagMapping).count()==1


def test_prior_hd_check_skips_remote_tags_and_cached_mappings_still_sync(environment,monkeypatch):
    from app import pixiv_check
    context, _, tmp_path = environment
    monkeypatch.setattr(pixiv_check,'get_db_context',context)
    path=tmp_path/'legacy.png';Image.new('RGB',(20,20),'red').save(path)
    with context() as db:
        db.add(models.Image(image_id='0000000001',pid='100',file_extension='png',file_path=str(path),pixiv_checked_at=datetime.utcnow()))
        db.add(models.PixivArtwork(account_revision='rev',pid='100',author_id='9',title='legacy',published_at=datetime.utcnow(),metadata_json=service.normalize_artwork(artwork()),origins=['recommendations']))
    monkeypatch.setattr(service,'client_for_job',lambda *args:pytest.fail('already checked image must not fetch tags'))
    result=pixiv_check.scan_next(1)
    assert result['status']=='complete' and result['auto_mappings']==1
    with context() as db:
        assert db.query(models.PixivTagMapping).count()==1
        image = db.get(models.Image, '0000000001')
        assert image.pid == '100_p0'
        assert image.pixiv_metadata.tags == [{'name':'游戏', 'translated_name':None}]
        assert [tag.name for tag in image.feature_tags] == ['Pixiv']
        assert image.groups == []  # Repair snapshots without reapplying work-level tags.
    assert pixiv_check.scan_next(1)['status'] == 'complete'


def test_checked_tag_backfill_preserves_page_labels_dates_and_unavailable_state(environment):
    from app.pixiv_metadata import backfill_checked_tags
    context, _, _ = environment
    checked = datetime(2026, 1, 1)
    with context() as db:
        db.add(models.Group(id=2,name='另一个作品'))
        db.add_all([models.Character(id=10,name='角色甲',group_id=1),models.Character(id=11,name='角色乙',group_id=2)])
        db.flush()
        art=service.normalize_artwork(artwork(tags=[{'name':'角色甲'},{'name':'角色乙'}],pages=2))
        db.add(models.PixivArtwork(account_revision='rev',pid='100',author_id='9',title='cached',published_at=checked,metadata_json=art,origins=[]))
        for index in range(3):
            work = '200' if index == 2 else '100'
            image=models.Image(image_id=f'{index+1:010d}',pid=f'{work}_p{min(index,1)}',file_extension='png',file_path='legacy.png',pixiv_checked_at=checked)
            image.pixiv_metadata=models.PixivImageMetadata(work_id=work,page_index=min(index,1),page_count=2,tags=[] if index != 1 else [{'name':'保留原标签'}],status='unavailable' if index==2 else 'verified',validated_at=checked)
            image.groups=[db.get(models.Group,1)]
            image.characters=[db.get(models.Character,10)]
            image.feature_tags=[db.get(models.FeatureTag,1)]
            db.add(image)
        db.flush()
        assert backfill_checked_tags(db)==2
        db.flush()
        assert backfill_checked_tags(db)==0
    with context() as db:
        for index in range(3):
            image=db.get(models.Image,f'{index+1:010d}')
            assert [c.id for c in image.characters]==[10]
            assert [g.id for g in image.groups]==[1]
            assert image.pixiv_checked_at==checked and image.pixiv_metadata.validated_at==checked
            assert image.local_checked_at is None
            if index==0: assert image.pixiv_metadata.tags==art['tags']
            if index==1: assert image.pixiv_metadata.tags==[{'name':'保留原标签'}]
            if index==2: assert image.pixiv_metadata.tags==[] and [t.name for t in image.feature_tags]==['白发']
            else: assert {t.name for t in image.feature_tags}=={'白发','Pixiv'}


def test_old_hd_only_check_without_cache_fetches_metadata_once(environment, monkeypatch):
    from app import pixiv_check
    context, _, tmp_path = environment
    monkeypatch.setattr(pixiv_check, 'get_db_context', context)
    install_fake(monkeypatch)
    path=tmp_path/'old_hd.png'
    Image.new('RGB', (32,20), 'red').save(path)
    with context() as db:
        db.add(models.Image(image_id='0000000001',pid='100',file_extension='png',file_path=str(path),pixiv_checked_at=datetime(2026,1,1)))
    assert pixiv_check.scan_next(1)['status']=='validated'
    monkeypatch.setattr(service,'client_for_job',lambda *args:pytest.fail('complete metadata must not be fetched again'))
    assert pixiv_check.scan_next(1)['status']=='complete'
    with context() as db:
        image=db.get(models.Image,'0000000001')
        assert image.pixiv_metadata.tags==service.normalize_artwork(artwork())['tags']
        assert 'Pixiv' in {tag.name for tag in image.feature_tags}


def test_cached_multipage_hd_marker_does_not_invent_page_confirmation(environment):
    from app.pixiv_metadata import backfill_checked_tags
    from app.pixiv_check import pending
    context, _, tmp_path=environment
    path=tmp_path/'legacy_multi.png'
    Image.new('RGB',(32,20),'red').save(path)
    with context() as db:
        image=models.Image(image_id='0000000001',pid='100',file_extension='png',file_path=str(path),pixiv_checked_at=datetime(2026,1,1))
        db.add(image)
        db.add(models.PixivArtwork(account_revision='rev',pid='100',author_id='9',title='cached',published_at=datetime.utcnow(),metadata_json=service.normalize_artwork(artwork(pages=2)),origins=[]))
        db.flush()
        assert backfill_checked_tags(db)==0
        assert image.pixiv_metadata is None and image.feature_tags==[]
        assert [row.image_id for row in pending(db)]==[image.image_id]


def test_local_validation_batches_archive_missing_move_orphans_and_set_only_local_marker(environment,monkeypatch):
    from app.local_check import run_batch
    context, client, tmp_path=environment
    from app.routers import system
    monkeypatch.setattr(system,'get_db_context',context)
    for attr in ['THUMB_PATH','PREVIEW_PATH']:monkeypatch.setattr(settings,attr,str(tmp_path/attr.lower()))
    root=Path(settings.STORE_PATH);root.mkdir(parents=True)
    live=root/'0000000001.png';Image.new('RGB',(25,20),'red').save(live)
    orphan=root/'orphan.png';Image.new('RGB',(15,15),'blue').save(orphan)
    with context() as db:
        db.add_all([models.Image(image_id='0000000001',pid='100',file_extension='png',file_path=str(live)),models.Image(image_id='0000000002',file_extension='png',file_path=str(root/'missing.png'))])
    with context() as db:
        result=run_batch(db,limit=1)
        assert result['ready']==1 and result['archived']==1 and result['orphans_moved']==1
        image=db.get(models.Image,'0000000001')
        assert image.local_checked_at is None and image.pixiv_checked_at is None
        assert db.get(models.Image,'0000000002').local_checked_at is None
        assert Path(settings.TEMP_PATH,'orphan.png').exists()
    assert client.post('/api/system/duplicates/scan?local_validation=true').status_code==200
    with context() as db:
        image=db.get(models.Image,'0000000001');assert image.local_checked_at
        image.width=99;db.flush();assert image.local_checked_at is None


def test_mapping_api_filters_and_rejects_wrong_character_scope(environment):
    context, client, _=environment
    with context() as db:
        db.add_all([models.Group(id=2,name='另一个分组'),models.Character(id=10,name='角色',group_id=1)])
    assert client.post('/api/pixiv-ol/tag-mappings',json={'tag':'角色','target_type':'character','target_id':10,'group_context':2}).status_code==422
    assert client.post('/api/pixiv-ol/tag-mappings',json={'tag':'角色','target_type':'character','target_id':10}).status_code==200
    rows=client.get('/api/pixiv-ol/tag-mappings?target_type=character&target_id=10').json()
    assert len(rows)==1 and rows[0]['group_context']==1 and rows[0]['tag']=='角色'


def test_character_mapping_moves_with_group_and_rejects_conflicts(environment):
    from app.tag_mappings import save_mapping
    from app.services import CharacterService
    from app.schemas import CharacterUpdate
    context, _, _=environment
    with context() as db:
        db.add_all([models.Group(id=2,name='目标分组'),models.Character(id=10,name='角色',group_id=1)])
        db.flush()
        save_mapping(db,'角色','character',10)
        CharacterService.update_character(db,10,CharacterUpdate(group_id=2))
        assert db.query(models.PixivTagMapping).one().group_context==2
        save_mapping(db,'角色','ignore',None,1)
        with pytest.raises(ValueError,match='映射冲突'):
            CharacterService.update_character(db,10,CharacterUpdate(group_id=1))
        assert db.get(models.Character,10).group_id==2
        assert db.query(models.PixivTagMapping).count()==2


def test_changed_local_content_removes_stale_pixiv_metadata(environment,monkeypatch):
    from app.local_check import run_batch
    context, _, tmp_path=environment
    for attr in ['THUMB_PATH','PREVIEW_PATH']:monkeypatch.setattr(settings,attr,str(tmp_path/attr.lower()))
    root=Path(settings.STORE_PATH);root.mkdir(parents=True)
    path=root/'0000000001.png';Image.new('RGB',(25,20),'red').save(path)
    with context() as db:
        db.add(models.Image(image_id='0000000001',pid='100_p0',file_extension='png',file_path=str(path),perceptual_hash='ffffffffffffffff',pixiv_checked_at=datetime.utcnow()))
        db.flush()
        db.add(models.PixivImageMetadata(image_id='0000000001',work_id='100',page_index=0,page_count=1,tags=[],validated_at=datetime.utcnow()))
    with context() as db:
        assert run_batch(db)['ready']==1
        image=db.get(models.Image,'0000000001')
        assert image.pixiv_checked_at is None and image.pixiv_metadata is None
        assert not image.pixiv_sources
