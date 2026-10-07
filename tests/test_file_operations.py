"""Transaction boundaries and actual process-crash recovery, using isolated files."""
import subprocess
import sys
import json
from pathlib import Path

import pytest
from PIL import Image
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app import models, schemas
from app.config import settings
from app.file_operations import FileOperation, recover
from app.services import ImageService


@pytest.fixture
def setup(tmp_path, monkeypatch):
    for setting, directory in [("BASE_DIR", ""), ("DATA_PATH", "data"), ("STORE_PATH", "store"),
                               ("THUMB_PATH", "thumbs"), ("PREVIEW_PATH", "previews")]:
        monkeypatch.setattr(settings, setting, str(tmp_path / directory))
    monkeypatch.setattr(settings, "STORAGE_BACKEND", "local")
    monkeypatch.setattr(ImageService, "generate_image_id", lambda: "1234567890")
    engine = create_engine(f"sqlite:///{tmp_path / 'operations.db'}")
    models.Base.metadata.create_all(engine)
    source = tmp_path / "source.png"
    Image.new("RGB", (20, 15), "red").save(source)
    yield sessionmaker(bind=engine), source, tmp_path
    engine.dispose()


@pytest.mark.parametrize("end", ["rollback", "close"])
def test_outer_transaction_preserves_retry_source_and_cleans_uncommitted_target(setup, end):
    factory, source, root = setup
    db = factory()
    image = ImageService.create_image(db, schemas.ImageCreate(), str(source), "source.png", "png",
                                     str(root / "store"), commit=False)
    db.add(models.PendingRequest(request_type="add", image_id=image.image_id, status="approved"))
    assert source.exists() and (root / "store" / "1234567890.png").exists()
    getattr(db, end)()
    db.close()
    with factory() as check:
        assert check.query(models.Image).count() == check.query(models.ImageJob).count() == 0
        assert check.query(models.PendingRequest).count() == 0
        assert check.query(models.FileOperationReceipt).count() == 0
    assert source.exists()
    assert not (root / "store" / "1234567890.png").exists()


def test_savepoint_does_not_consume_source_before_outer_commit(setup):
    factory, source, root = setup
    with factory() as db:
        with db.begin_nested():
            image = ImageService.create_image(db, schemas.ImageCreate(), str(source), "source.png", "png",
                                             str(root / "store"), commit=False)
        assert source.exists()
        db.add(models.PendingRequest(request_type="add", image_id=image.image_id, status="approved"))
        db.commit()
    assert not source.exists()
    with factory() as db:
        assert db.query(models.Image).count() == db.query(models.PendingRequest).count() == 1
        assert db.query(models.ImageJob).count() == 2


def test_delete_rollback_keeps_original_and_derivatives(setup):
    factory, source, root = setup
    with factory() as db:
        db.add(models.Image(image_id="1234567890", file_extension="png", file_path=str(source)))
        db.commit()
        image = db.get(models.Image, "1234567890")
        thumb = Path(ImageService.thumb_path(image))
        thumb.write_bytes(b"old preview")
        ImageService.delete_image(db, image.image_id, str(root), commit=False)
        assert source.exists() and thumb.exists()
        db.rollback()
        assert db.get(models.Image, "1234567890") is not None
        assert source.exists() and thumb.exists()


def test_pending_review_file_publication_rolls_back(setup):
    factory, source, root = setup
    target = root / "pending" / "review.png"
    with factory() as db:
        FileOperation.stage_pending(db, source, target)
        assert target.exists() and source.exists()
        db.rollback()
    assert source.exists() and not target.exists()


def test_recovery_skips_live_lease_and_keeps_replaced_source(setup):
    factory, source, root = setup
    with factory() as db:
        operation = FileOperation.prepare(db, "discard", source=source)
        assert recover(db) == 0
        source.write_bytes(b"different file that must survive")
        db.commit()
        assert not operation.path.exists()
    assert source.read_bytes() == b"different file that must survive"


@pytest.mark.parametrize("committed", [False, True])
def test_recover_after_process_dies_before_or_after_commit(setup, committed):
    factory, source, root = setup
    code = '''
import os, sys
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from app import models, schemas
from app.config import settings
from app.file_operations import FileOperation
from app.services import ImageService
from pathlib import Path
root=Path(sys.argv[1])
settings.BASE_DIR=str(root);settings.DATA_PATH=str(root/'data')
settings.STORE_PATH=str(root/'store');settings.STORAGE_BACKEND='local'
ImageService.generate_image_id=staticmethod(lambda:'1234567890')
engine=create_engine(f"sqlite:///{root/'operations.db'}")
db=Session(engine)
ImageService.create_image(db,schemas.ImageCreate(),str(root/'source.png'),'source.png','png',str(root/'store'),commit=False)
if sys.argv[2]=='1':
    FileOperation.finish=lambda self: False
    db.commit()
os._exit(17)
'''
    result = subprocess.run([sys.executable, "-c", code, str(root), str(int(committed))],
                            cwd=Path(__file__).resolve().parents[1], capture_output=True, timeout=30)
    assert result.returncode == 17, result.stderr.decode(errors="replace")
    assert source.exists() and (root / "store" / "1234567890.png").exists()
    with factory() as db:
        assert recover(db) == 1
        assert bool(db.get(models.Image, "1234567890")) == committed
        assert db.query(models.FileOperationReceipt).count() == 0
    assert source.exists() != committed
    assert (root / "store" / "1234567890.png").exists() == committed
    assert not list((root / "data").rglob("*.json"))


def test_independent_worker_recovers_deferred_source_cleanup(setup, monkeypatch):
    from app import database, file_operations
    factory, source, root = setup
    with factory() as db:
        operation = FileOperation.prepare(db, "discard", source=source)

        def temporary_error():
            raise OSError("synthetic cleanup unavailable")

        operation._reconcile = temporary_error
        db.commit()
    assert source.exists() and operation.path.exists()
    retry = json.loads(operation.path.read_text())["retry_after"]
    monkeypatch.setattr(file_operations.time, "time", lambda: retry + 1)
    monkeypatch.setattr(database, "SessionLocal", factory)
    assert file_operations.FileOperationWorker().run_once() == 1
    assert not source.exists() and not operation.path.exists()


def test_recovery_defers_changed_r2_configuration(setup, monkeypatch):
    from types import SimpleNamespace
    from app import file_operations
    factory, source, root = setup
    monkeypatch.setattr(settings, "STORAGE_BACKEND", "r2")
    monkeypatch.setattr(settings, "R2_BUCKET", "old-bucket")
    with factory() as db:
        operation = FileOperation.prepare(db, "delete", locator="r2://old-bucket/images/test.png")

        def temporary_error():
            raise TimeoutError("synthetic timeout")

        operation._reconcile = temporary_error
        db.commit()
        retry = json.loads(operation.path.read_text())["retry_after"]
        monkeypatch.setattr(file_operations.time, "time", lambda: retry + 1000)
        monkeypatch.setattr(settings, "R2_BUCKET", "new-bucket")
        deleted = []
        monkeypatch.setattr(file_operations, "get_image_storage", lambda *a, **kw: SimpleNamespace(delete=deleted.append))
        assert recover(db) == 0
        assert not deleted and operation.path.exists()
        monkeypatch.setattr(settings, "R2_BUCKET", "old-bucket")
        monkeypatch.setattr(file_operations.time, "time", lambda: retry + 2000)
        assert recover(db) == 1
        assert deleted == ["images/test.png"]
