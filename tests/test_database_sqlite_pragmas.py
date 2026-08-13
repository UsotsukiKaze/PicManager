from sqlalchemy import create_engine, event

from app import database


def _configured_engine(url):
    engine = create_engine(
        url,
        connect_args={
            "check_same_thread": False,
            "timeout": database.SQLITE_BUSY_TIMEOUT_MS / 1000,
        },
    )
    event.listen(engine, "connect", database._configure_sqlite_connection)
    return engine


def test_file_sqlite_enables_wal_and_busy_timeout(tmp_path):
    engine = _configured_engine(f"sqlite:///{tmp_path / 'wal.db'}")

    assert database.enable_sqlite_wal(engine) is True
    with engine.connect() as connection:
        assert connection.exec_driver_sql("PRAGMA journal_mode").scalar_one().lower() == "wal"
        assert connection.exec_driver_sql("PRAGMA busy_timeout").scalar_one() == database.SQLITE_BUSY_TIMEOUT_MS
    engine.dispose()


def test_memory_sqlite_keeps_memory_journal_and_sets_busy_timeout():
    engine = _configured_engine("sqlite:///:memory:")

    assert database.enable_sqlite_wal(engine) is False
    with engine.connect() as connection:
        assert connection.exec_driver_sql("PRAGMA journal_mode").scalar_one().lower() == "memory"
        assert connection.exec_driver_sql("PRAGMA busy_timeout").scalar_one() == database.SQLITE_BUSY_TIMEOUT_MS
        connection.exec_driver_sql("CREATE TABLE smoke_test (id INTEGER PRIMARY KEY)")
    engine.dispose()


def test_sqlite_backup_includes_committed_wal_rows(tmp_path):
    live_path = tmp_path / "live.db"
    snapshot_path = tmp_path / "snapshot.db"
    engine = _configured_engine(f"sqlite:///{live_path}")
    assert database.enable_sqlite_wal(engine) is True

    with engine.begin() as connection:
        connection.exec_driver_sql("CREATE TABLE state (value TEXT NOT NULL)")
        connection.exec_driver_sql("INSERT INTO state (value) VALUES ('committed-in-wal')")

    assert database._atomic_sqlite_backup(str(live_path), str(snapshot_path), overwrite=True) is True
    snapshot_engine = create_engine(f"sqlite:///{snapshot_path}")
    with snapshot_engine.connect() as connection:
        assert connection.exec_driver_sql("SELECT value FROM state").scalar_one() == "committed-in-wal"
        assert connection.exec_driver_sql("PRAGMA quick_check").scalar_one() == "ok"
    snapshot_engine.dispose()
    engine.dispose()
