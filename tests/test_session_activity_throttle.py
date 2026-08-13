from datetime import datetime, timedelta
from types import SimpleNamespace

from app.routers import auth


class _FakeQuery:
    def __init__(self, session):
        self.session = session

    def filter(self, *args):
        return self

    def first(self):
        return self.session


class _FakeDb:
    def __init__(self, session):
        self.session = session
        self.commits = 0

    def query(self, model):
        return _FakeQuery(self.session)

    def commit(self):
        self.commits += 1

    def delete(self, value):
        raise AssertionError("active session must not be deleted")


def _session(last_activity):
    return SimpleNamespace(
        session_id="session",
        user_id=1,
        guest_ip=None,
        guest_name=None,
        is_guest="false",
        created_at=datetime.utcnow() - timedelta(days=1),
        last_activity=last_activity,
        expires_at=datetime.utcnow() + timedelta(days=1),
    )


def test_recent_session_read_does_not_write_database():
    record = _session(datetime.utcnow() - timedelta(minutes=1))
    db = _FakeDb(record)

    assert auth.get_session(db, "session") is not None
    assert db.commits == 0


def test_stale_session_activity_is_refreshed_once():
    original = datetime.utcnow() - timedelta(minutes=10)
    record = _session(original)
    db = _FakeDb(record)

    assert auth.get_session(db, "session") is not None
    assert db.commits == 1
    assert record.last_activity > original
