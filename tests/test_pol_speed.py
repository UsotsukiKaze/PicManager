import threading

from sqlalchemy import create_engine, update
from sqlalchemy.orm import Session

from app import database, models
from app.integrations.pixiv_ol import strategies, profile_cache, scheduling
from app.integrations.pixiv_ol.recommendations import TagIndex
from app.snapshot_worker import SnapshotWorker
from tests.test_pixiv_ol import environment


def test_only_successful_writes_count_towards_snapshot(monkeypatch):
    engine = create_engine('sqlite:///:memory:')
    models.Base.metadata.create_all(engine)
    calls = []
    monkeypatch.setattr(database, 'engine', engine)
    monkeypatch.setattr(database, 'register_db_commit', lambda: calls.append(1))
    with Session(engine) as db:
        db.query(models.Group).all(); db.commit()
        assert calls == []
        db.add(models.Group(name='first')); db.commit()
        assert calls == [1]
        row = db.query(models.Group).first()
        row.name = 'first'; db.commit()
        assert calls == [1]
        row.name = 'rolled back'; db.flush(); db.rollback(); db.commit()
        assert calls == [1]
        db.execute(update(models.Group).values(name='bulk')); db.commit()
        assert calls == [1, 1]
        db.execute(update(models.Group).where(models.Group.id == -1).values(name='nothing')); db.commit()
        assert calls == [1, 1]
    engine.dispose()


def test_snapshot_requests_return_while_backup_is_busy_and_coalesce():
    started, release, second = threading.Event(), threading.Event(), threading.Event()
    calls = []
    def backup():
        calls.append(1)
        if len(calls) == 1:
            started.set(); assert release.wait(5)
        else:
            second.set()
        return True
    writer = SnapshotWorker(backup, interval=.03, debounce=.01)
    try:
        writer.request(); assert started.wait(2)
        for _ in range(20): writer.request()
        assert len(calls) == 1
        release.set(); assert second.wait(2)
        assert len(calls) == 2
    finally:
        release.set(); writer.stop()


def test_profiles_reuse_results_but_invalidate_for_training_edits(environment, monkeypatch):
    context, _, _ = environment
    builds = []
    def build(*_):
        builds.append(1)
        return {'vectors': {'feature': {1: len(builds)}}}
    monkeypatch.setattr(strategies, 'personal_profile', build)
    def profile():
        with context() as db:
            return strategies.build_profile(db, TagIndex(db), db.get(models.PixivAccount, 1), 'personal')
    first = profile(); first['vectors']['feature'].clear()
    assert profile()['vectors']['feature'] == {1: 1}
    with context() as db:
        account = db.get(models.PixivAccount, 1)
        account.sync_state = {'pending_sync': True}
        assert strategies.build_profile(db, TagIndex(db), account, 'personal')['vectors']['feature'] == {1: 1}
    with context() as db:
        account = db.get(models.PixivAccount, 1)
        account.sync_state = {'poll': 1}
    assert profile()['vectors']['feature'] == {1: 1}
    with context() as db:
        db.add(models.PixivFeedback(actor_id=1, account_revision='rev', pid='100', value='like'))
    assert profile()['vectors']['feature'] == {1: 2}
    with context() as db:
        db.get(models.PixivAccount, 1).preferences = {'max_restrict': 1}
    assert profile()['vectors']['feature'] == {1: 3}
    with context() as db:
        db.get(models.FeatureTag, 1).name = 'changed'
    assert profile()['vectors']['feature'] == {1: 4}
    with context() as db:
        db.query(models.PixivFeedback).delete()
    assert profile()['vectors']['feature'] == {1: 5}
    clock = profile_cache.time.monotonic()
    monkeypatch.setattr(profile_cache.time, 'monotonic', lambda: clock + profile_cache.TTL + 1)
    assert profile()['vectors']['feature'] == {1: 6}


def test_corpus_cache_survives_likes_but_mapping_edits_change_its_key(environment):
    context, _, _ = environment
    builds = []
    def corpus():
        builds.append(1)
        return {'size': len(builds)}
    def result():
        with context() as db:
            return profile_cache.cached_profile(db, TagIndex(db), db.get(models.PixivAccount, 1),
                'tag-frequency', corpus, training_sensitive=False)
    assert result() == {'size': 1}
    with context() as db:
        db.add(models.PixivFeedback(actor_id=1, account_revision='rev', pid='100', value='like'))
    assert result() == {'size': 1}
    with context() as db:
        db.get(models.FeatureTag, 1).name = 'new mapping input'
    assert result() == {'size': 2}


def test_diversity_schedule_normalizes_each_item_once(monkeypatch):
    calls = []
    normalize = scheduling.normalize
    monkeypatch.setattr(scheduling, 'normalize', lambda value: (calls.append(value), normalize(value))[1])
    pool = [{'pid': str(n), 'author_id': str(n), 'tags': [{'name': 'COMMON'}, {'name': str(n)}],
             'match': {'character_ids': [n % 3]}, '_score': 1-n/1000} for n in range(30)]
    chosen, tag_sets = [], {}
    from collections import Counter
    authors = Counter()
    for _ in range(20):
        item = scheduling.take(pool, chosen, authors, role_cap=True, tag_sets=tag_sets)
        chosen.append(item); authors[item['author_id']] += 1
    assert len(calls) == 60
    assert len({i['pid'] for i in chosen}) == 20
    assert not any('_scheduling_tags' in i for i in chosen)
