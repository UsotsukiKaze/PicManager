import sqlite3

from app import database


def _write_value(path, value):
    with sqlite3.connect(path) as db:
        db.execute("CREATE TABLE IF NOT EXISTS state (value TEXT NOT NULL)")
        db.execute("DELETE FROM state")
        db.execute("INSERT INTO state (value) VALUES (?)", (value,))


def _read_value(path):
    with sqlite3.connect(path) as db:
        return db.execute("SELECT value FROM state").fetchone()[0]


def test_snapshot_creation_uses_consistent_sqlite_backup(monkeypatch, tmp_path):
    live_path = tmp_path / "picmanager.db"
    _write_value(live_path, "current")
    monkeypatch.setattr(database, "DATABASE_PATH", str(live_path))

    assert database.create_db_snapshot() is True
    assert _read_value(tmp_path / "picmanager.db.snapshot") == "current"


def test_missing_database_is_restored_from_snapshot(monkeypatch, tmp_path):
    live_path = tmp_path / "picmanager.db"
    snapshot_path = tmp_path / "picmanager.db.snapshot"
    _write_value(snapshot_path, "snapshot")
    monkeypatch.setattr(database, "DATABASE_PATH", str(live_path))

    assert database.restore_snapshot_if_needed() is True
    assert _read_value(live_path) == "snapshot"


def test_existing_newer_database_is_never_replaced(monkeypatch, tmp_path):
    live_path = tmp_path / "picmanager.db"
    snapshot_path = tmp_path / "picmanager.db.snapshot"
    _write_value(live_path, "new-live-data")
    _write_value(snapshot_path, "old-snapshot")
    monkeypatch.setattr(database, "DATABASE_PATH", str(live_path))

    assert database.restore_snapshot_if_needed() is False
    assert _read_value(live_path) == "new-live-data"
