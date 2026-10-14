from contextlib import contextmanager
from datetime import datetime

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app import group_covers, models
from app.integrations.pixiv_ol import jobs, service
from app.routers.public_api import groups


@pytest.fixture
def library(monkeypatch):
    engine = create_engine("sqlite:///:memory:")
    models.Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    @contextmanager
    def context():
        with Session() as db:
            yield db
            db.commit()
    for module in (groups, jobs, service):
        monkeypatch.setattr(module, "get_db_context", context)
    with context() as db:
        db.add_all([models.Group(id=1, name="作品一"), models.Group(id=2, name="作品二"),
                    models.User(id=1, qq_number="123", role="root")])
    yield context
    engine.dispose()


def image(db, number, *, group=1, rating="r12", width=1600, height=900, status="available", preview="ready"):
    row = models.Image(image_id=f"{number:010d}", pid=f"{1000 + number}_p0", file_extension="jpg",
                       file_path=f"resource/store/{number}.jpg", age_rating=rating, width=width, height=height,
                       file_status=status, preview_status=preview)
    row.groups = [db.get(models.Group, group)]
    db.add(row)
    return row


def connect(db):
    account = models.PixivAccount(id=1, user_id="7", name="Root", owner_id=1, revision="cover-rev",
                                  credential="unused", sync_state={}, status="connected")
    db.add(account)
    return account


def cached(db, pid, bookmarks, *, rating=0, revision="cover-rev"):
    db.add(models.PixivArtwork(account_revision=revision, pid=pid, author_id="9", title="测试",
           published_at=datetime.utcnow(), metadata_json={"bookmarks": bookmarks, "x_restrict": rating}, origins=[]))


def test_covers_filter_exact_r12_landscape_and_rank_cached_bookmarks(library):
    with library() as db:
        connect(db)
        best = image(db, 1, width=1400, height=900)
        image(db, 2)
        for number, options in [(3, {"rating": "r18"}), (4, {"rating": "all"}),
                               (5, {"width": 800, "height": 1000}), (6, {"status": "archived"}),
                               (7, {"group": 2}), (8, {"height": 0})]:
            image(db, number, **options)
        for n in range(1, 9):
            cached(db, str(1000 + n), 100 if n == 1 else 20 if n == 2 else 99999)
        db.flush()
        result = group_covers.attach_covers(db, [{"id": 1}])
        assert result[0]["cover"]["image_id"] == best.image_id
        assert result[0]["cover"]["bookmarks"] == 100
        assert result[0]["cover"]["source"] == "pixiv_bookmarks"
        assert result[0]["cover_refreshing"] is False
        assert db.query(models.PixivJob).count() == 0


def test_local_cover_prefers_wide_ready_preview_and_inferred_group(library):
    with library() as db:
        image(db, 1, width=1500, height=1000)
        best = image(db, 2)
        best.groups = []
        best.characters = [models.Character(name="角色", group_id=1)]
        image(db, 3, preview="pending")
        db.flush()
        result = group_covers.attach_covers(db, [{"id": 1}, {"id": 2}])
        assert result[0]["cover"]["image_id"] == best.image_id
        assert result[0]["cover"]["source"] == "local"
        assert result[1]["cover"] is None
        assert db.query(models.PixivJob).count() == 0


def test_popular_groups_count_direct_and_character_links_once(library):
    with library() as db:
        first = image(db, 1)
        first.characters = [models.Character(name="角色", group_id=1)]
        image(db, 2)
        image(db, 3, group=2)
        image(db, 4, status="archived")
    result = groups.get_popular_groups(include_covers=True)
    assert [(row["id"], row["image_count"]) for row in result] == [(1, 2), (2, 1)]
    assert all(row["cover"] for row in result)
    assert "cover" not in groups.get_popular_groups()[0]


def test_refresh_jobs_are_bounded_and_deduplicated(library):
    with library() as db:
        connect(db)
        for number in range(1, 30):
            image(db, number, group=1 if number % 2 else 2)
        db.flush()
        result = group_covers.attach_covers(db, [{"id": 1}, {"id": 2}])
        db.flush()
        group_covers.attach_covers(db, [{"id": 1}, {"id": 2}])
        assert all(row["cover_refreshing"] for row in result)
        job = db.query(models.PixivJob).one()
        assert job.kind == "home_covers"
        assert len(job.payload["pids"]) == group_covers.REQUESTS_PER_JOB
        assert job.payload["pids"][0] != job.payload["pids"][1]


def test_worker_fetches_details_and_persists_popularity(library, monkeypatch):
    calls = []
    class Provider:
        def call(self, method, **kwargs):
            calls.append((method, kwargs))
            return {"illust": {"id": int(kwargs["illust_id"]), "title": "封面", "user": {"id": 9, "name": "画师"},
                    "create_date": datetime.utcnow().isoformat(), "x_restrict": 0, "total_bookmarks": 888}}
        def close(self):
            pass
    monkeypatch.setattr(service, "client_for_job", lambda *_: Provider())
    with library() as db:
        connect(db)
        image(db, 1)
        db.flush()
        group_covers.attach_covers(db, [{"id": 1}])
    assert jobs.Worker().run_once() is True
    assert calls == [("illust_detail", {"illust_id": "1001"})]
    with library() as db:
        assert db.query(models.PixivJob).one().status == "completed"
        result = group_covers.attach_covers(db, [{"id": 1}])
        assert result[0]["cover"]["bookmarks"] == 888
        assert result[0]["cover_refreshing"] is False


def test_cached_restricted_work_and_revoked_owner_are_not_used(library):
    with library() as db:
        connect(db)
        image(db, 1)
        cached(db, "1001", 9999, rating=1)
        db.get(models.User, 1).role = "user"
        db.flush()
        result = group_covers.attach_covers(db, [{"id": 1}])
        assert result[0]["cover"] is None
        assert db.query(models.PixivJob).count() == 0
