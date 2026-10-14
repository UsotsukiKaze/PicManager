from datetime import datetime, timedelta
from types import SimpleNamespace

import pytest

from test_pixiv_ol import environment, artwork
from test_pixiv_recommendation_preferences import image, mapping, cached, like
from app import models
from app.integrations.pixiv_ol import service, strategies, learning, bookmarks
from app.integrations.pixiv_ol.recommendations import TagIndex


def test_quality_distinguishes_1000_and_10000_and_missing_data_is_not_zero():
    now = datetime.utcnow()
    art = {"published_at": now.isoformat(), "bookmarks": 1000}
    assert learning.quality({**art, "bookmarks": 10000}, now) > learning.quality(art, now) > 0.5
    assert learning.quality({**art, "bookmarks": None}, now) > 0.0


def test_sparse_group_rate_uses_prior_and_negative_growth_is_not_rewarded():
    now = datetime.utcnow()
    items = [
        {
            "bookmarks": n * 10,
            "views": n * 1000,
            "published_at": now.isoformat(),
            "x_restrict": 0,
            "bookmark_velocity": n,
            "match": {"group_ids": [1]},
        }
        for n in range(1, 101)
    ]
    ref = learning.QualityReference(items, now)
    candidate = {**items[20], "views": 30, "bookmarks": 20, "bookmark_velocity": 0}
    assert learning.quality(candidate, now, ref) < learning.quality(items[90], now, ref)


def test_cart_automatic_like_is_not_counted_again_as_remote_favorite(environment):
    context, _, _ = environment
    with context() as db:
        art = cached(db, "800", ["Atmosphere"])
        cached(db, "801", ["Other"])
        db.add(
            models.PixivCartItem(id="cart", actor_id=1, account_revision="rev", pid="800", pages=[0], metadata_json=art)
        )
        account = db.get(models.PixivAccount, 1)
        bookmarks.intent(db, account, 1, "800", True, "auto_cart")
        db.flush()
        before = strategies.personal_profile(db, TagIndex(db), account, [])
        like(db, "800")
        db.flush()
        after = strategies.personal_profile(db, TagIndex(db), account, [])
        assert before["vectors"] == after["vectors"]
        assert db.query(models.PixivBookmarkState).one().source == "auto_cart"


def test_group_features_and_role_backoff_do_not_mix_all_series(environment):
    context, _, _ = environment
    with context() as db:
        db.add(models.Group(id=2, name="第二分组"))
        db.add(models.FeatureTag(id=2, name="另一特征"))
        db.add_all(
            [models.Character(id=10, name="角色甲", group_id=1), models.Character(id=20, name="角色乙", group_id=2)]
        )
        db.flush()
        for n in range(50):
            image(db, f"{n+1:010d}", str(n + 1000), role=10, features=[1])
            row = image(db, f"{n+101:010d}", str(n + 2000), role=20, features=[2])
            row.groups = [db.get(models.Group, 2)]
        db.flush()
        profile = strategies.personal_profile(db, TagIndex(db), db.get(models.PixivAccount, 1), strategies.library(db))
        assert profile["group_features"][1][1] > profile["group_features"][1][2]
        assert profile["group_features"][2][2] > profile["group_features"][2][1]
        assert profile["role_features"][10][1] > profile["role_features"][10][2]


def test_stock_probabilities_sum_to_one_and_page_does_not_round_away_exploration(environment):
    context, _, _ = environment
    with context() as db:
        db.add(models.Character(id=10, name="角色", group_id=1))
        db.flush()
        profile = strategies.build_profile(db, TagIndex(db), db.get(models.PixivAccount, 1), "stock")
        profile["policy_version"] = strategies.STOCK_POLICY_VERSION
        strategies.stock_schedule([], profile, TagIndex(db))
        assert sum(profile["bucket_probabilities"].values()) == pytest.approx(1)
        assert profile["new_character_fractions"][1] <= 0.8
        rows = [(n, {"stock_pool": "new_group" if n % 20 == 0 else "known"}) for n in range(60)]
        assert strategies.stock_page(rows[20:], 20, profile) == rows[20:40]


def test_metrics_sampling_has_six_hour_minimum_and_measures_growth(environment):
    context, _, _ = environment
    raw = artwork()
    raw.update(total_bookmarks=1000, total_view=10000)
    service.save_artworks("rev", [raw], "recommended_personal_1", 1)
    with context() as db:
        metric = db.query(models.PixivArtworkMetric).one()
        metric.sampled_at = datetime.utcnow() - timedelta(hours=7)
    raw["total_bookmarks"] = 1700
    service.save_artworks("rev", [raw], "recommended_personal_1", 1)
    service.save_artworks("rev", [raw], "recommended_personal_1", 1)
    with context() as db:
        assert db.query(models.PixivArtworkMetric).count() == 2
        art = db.query(models.PixivArtwork).one().metadata_json
        assert art["bookmark_velocity"] == pytest.approx(100, rel=0.001)


def test_popular_search_rejection_falls_back_without_starving_other_sources(environment):
    context, _, _ = environment

    class Remote:
        cursor = staticmethod(lambda value: {})

        def __init__(self):
            self.calls = []

        def call(self, method, **params):
            from app.integrations.pixiv_ol.provider import PixivError

            self.calls.append((method, params))
            if method == "search_illust" and params.get("sort") == "popular_desc":
                raise PixivError("access_denied")
            return {"illusts": [artwork()], "next_url": None}

    remote = Remote()
    with context() as db:
        mapping(db, "GameNative", "group", 1)
    service.refresh_candidates(remote, "rev", 1, "personal", progressive=False)
    assert any(m == "search_illust" and p.get("sort") == "date_desc" for m, p in remote.calls)
    assert any(m == "illust_ranking" for m, p in remote.calls)


def test_recall_budget_preserves_related_and_ranking_in_long_tag_queues():
    from app.integrations.pixiv_ol.recall import wave

    queries = [{"source": "search", "word": str(n)} for n in range(100)] + [
        {"source": "ranking", "word": str(n)} for n in range(100)
    ]
    seeds = list(map(str, range(100)))
    counts = {}
    for _ in range(22):
        picked, related, counts = wave(queries, seeds, counts, limit=3)
        for query in picked:
            queries.remove(query)
        for seed in related:
            seeds.remove(seed)
    assert abs(counts["search"] / 66 - 0.30 / 0.65) < 0.03
    assert abs(counts["related"] / 66 - 0.25 / 0.65) < 0.03
    assert abs(counts["ranking"] / 66 - 0.10 / 0.65) < 0.03


def test_mapping_change_invalidates_current_batch_but_keeps_explicit_reading_batch(environment):
    from test_pixiv_ol import FakeProvider

    context, client, _ = environment
    result = service.refresh_candidates(FakeProvider("test"), "rev", 1, "personal")
    assert client.get("/api/pixiv-ol/recommendations?mode=personal").json()["items"]
    with context() as db:
        mapping(db, "NewNative", "group", 1)
    assert client.get("/api/pixiv-ol/recommendations?mode=personal").json()["batch_id"] is None
    assert client.get(
        "/api/pixiv-ol/recommendations", params={"mode": "personal", "batch_id": result["batch_id"]}
    ).json()["items"]


def test_actual_short_supply_cannot_exceed_eighty_percent_or_five_percent():
    from test_pixiv_recommendation_modes import stock_fixture

    items, profile, index = stock_fixture(known=1, unknown_role=100, unknown_group=100)
    profile.update(
        policy_version=strategies.STOCK_POLICY_VERSION, new_character_fractions={g: 0.8 for g in profile["quotas"]}
    )
    for item in items:
        item.update(tags=[], _quality=1)
    chosen = strategies.stock_schedule(items, profile, index)
    new_roles = sum(i["stock_pool"] == "new_character" for i in chosen)
    new_groups = sum(i["stock_pool"] == "new_group" for i in chosen)
    assert chosen and new_roles / len(chosen) <= 0.8
    assert new_groups / len(chosen) <= 0.05


def test_exposure_debt_prioritizes_underexposed_group_on_next_refresh():
    from test_pixiv_recommendation_modes import stock_fixture

    def schedule(history):
        items, profile, index = stock_fixture(known=400, unknown_role=0, unknown_group=0)
        profile.update(
            policy_version=strategies.STOCK_POLICY_VERSION,
            new_character_fractions={g: 0 for g in profile["quotas"]},
            quota_history=history,
        )
        for item in items:
            item.update(tags=[], _quality=1)
        return strategies.stock_schedule(items, profile, index)

    assert schedule({})[0]["primary_group"] == 1
    assert schedule({str(("known", 1, 11)): 500})[0]["primary_group"] == 2
