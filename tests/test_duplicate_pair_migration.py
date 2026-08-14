from sqlalchemy import create_engine, text

from app import database, models


def test_duplicate_pair_migration_creates_decision_table_and_hash_index(monkeypatch, tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'migration.db'}")
    with engine.begin() as connection:
        models.Base.metadata.create_all(connection)
        connection.execute(text("DROP TABLE duplicate_pair_decisions"))
        connection.execute(text("DROP INDEX IF EXISTS ix_images_perceptual_hash"))

    monkeypatch.setattr(database, "engine", engine)
    database.apply_migrations()

    with engine.connect() as connection:
        tables = {row[0] for row in connection.execute(text("SELECT name FROM sqlite_master WHERE type='table'"))}
        indexes = {row[0] for row in connection.execute(text("SELECT name FROM sqlite_master WHERE type='index'"))}

    assert "duplicate_pair_decisions" in tables
    assert "ix_images_perceptual_hash" in indexes
