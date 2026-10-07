"""Crash-recoverable file intents with database commit witnesses and OS leases.

Persist intent before touching storage, add a receipt to the caller's transaction,
then reconcile after its outer transaction ends. Expensive storage work never
runs while the cleanup reader owns a database write transaction.
"""

import hashlib
import json
import os
import threading
import time
import uuid
from pathlib import Path

from sqlalchemy import event, select, delete
from sqlalchemy.orm import Session

from . import models
from .config import settings
from .logger import log_error
from .storage import get_image_storage, LocalStorage

_guard = threading.Lock()
_active = set()


def _directory(bind):
    scope = hashlib.sha256(str(bind.url).encode()).hexdigest()[:24]
    return Path(settings.DATA_PATH) / "file-operations" / scope


def _signature(path):
    try:
        stat = Path(path).stat()
        return [stat.st_dev, stat.st_ino, stat.st_size, stat.st_mtime_ns]
    except FileNotFoundError:
        return None


def _lease(path):
    with _guard:
        if str(path) in _active:
            return None
        handle = path.with_suffix(".lock").open("a+b")
        try:
            if handle.tell() == 0:
                handle.write(b"0")
                handle.flush()
            handle.seek(0)
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            handle.close()
            return None
        _active.add(str(path))
        return handle


class FileOperation:
    def __init__(self, path, record, bind, handle, backend=None):
        self.path, self.record, self.bind = path, record, bind
        self.handle, self.backend = handle, backend

    @classmethod
    def prepare(cls, db, kind, *, image_id=None, locator=None, key=None, source=None,
                source_key=None, root=None, backend=None, derivatives=(), attach=True, backend_kind=None):
        bind = db.get_bind()
        if not hasattr(bind, "url"):
            raise ValueError("File operations require an engine-bound Session")
        directory = _directory(bind)
        directory.mkdir(parents=True, exist_ok=True)
        token = uuid.uuid4().hex
        path = directory / f"{token}.json"
        record = dict(id=token, kind=kind, image_id=image_id, locator=locator, key=key,
                      source=os.path.abspath(source) if source else None,
                      source_signature=_signature(source) if source else None, source_key=source_key,
                      root=str(Path(root or settings.STORE_PATH).resolve()),
                      backend=backend_kind or str(settings.STORAGE_BACKEND).lower(),
                      base_dir=str(Path(settings.BASE_DIR).resolve()),
                      r2=[settings.R2_ACCOUNT_ID, settings.R2_BUCKET, settings.R2_PREFIX],
                      derivatives=[str(Path(item).resolve()) for item in derivatives])
        operation = cls(path, record, bind, _lease(path), backend)
        if operation.handle is None:
            raise RuntimeError("file_operation_lease_unavailable")
        try:
            operation._save()
            if attach:
                operation.attach(db)
            return operation
        except BaseException:
            operation.release()
            raise

    def _save(self):
        temporary = self.path.with_suffix(".writing")
        try:
            with temporary.open("w", encoding="utf-8") as output:
                os.chmod(temporary, 0o600)
                json.dump(self.record, output)
                output.flush()
                os.fsync(output.fileno())
            os.replace(temporary, self.path)
            if os.name != "nt":
                descriptor = os.open(self.path.parent, os.O_RDONLY)
                try:
                    os.fsync(descriptor)
                finally:
                    os.close(descriptor)
        finally:
            temporary.unlink(missing_ok=True)

    def attach(self, db):
        db.info.setdefault("file_operations", []).append(self)
        db.add(models.FileOperationReceipt(id=self.record["id"]))

    def published(self, stored):
        self.record["locator"] = stored.locator
        self.record["key"] = stored.key
        if stored.locator.startswith("r2://"):
            self.record["backend"] = "r2"
        self._save()

    def _backend(self):
        if self.backend is not None:
            return self.backend
        if self.record["backend"] == "local":
            return LocalStorage(self.record["root"], base_dir=self.record.get("base_dir"))
        if self.record["backend"] != str(settings.STORAGE_BACKEND).lower():
            raise RuntimeError("storage_configuration_changed")
        if self.record["backend"] == "r2" and self.record["r2"] != [
            settings.R2_ACCOUNT_ID, settings.R2_BUCKET, settings.R2_PREFIX,
        ]:
            raise RuntimeError("storage_configuration_changed")
        return get_image_storage(settings, local_root=self.record["root"])

    @classmethod
    def stage_pending(cls, db, source, target):
        """Keep retry input until the review request and its new file commit together."""
        target = Path(target)
        backend = LocalStorage(target.parent, base_dir=settings.BASE_DIR)
        operation = cls.prepare(db, "publish", source=source, key=target.name,
                                root=target.parent, backend=backend, backend_kind="local")
        operation.published(backend.put_file(source, target.name))

    def finish(self):
        try:
            self._reconcile()
        except Exception as error:
            # Retain the durable intent and receipt for the next recovery pass.
            log_error(f"File operation deferred: type={type(error).__name__}")
            self.record["attempts"] = self.record.get("attempts", 0) + 1
            self.record["retry_after"] = time.time() + min(300, 2 ** min(self.record["attempts"], 8))
            try:
                self._save()
            except OSError:
                pass  # Original intent remains recoverable if the disk is unavailable.
            return False
        finally:
            self.release()
        return True

    def _reconcile(self):
        record = self.record
        with Session(self.bind) as db:
            committed = db.get(models.FileOperationReceipt, record["id"]) is not None
            locator = record.get("locator")
            referenced = locator and db.scalar(select(models.Image.image_id).where(
                models.Image.file_path == locator, models.Image.file_status == "available",
            ).limit(1)) is not None
            image = db.get(models.Image, record["image_id"]) if record.get("image_id") else None
            derivatives_unused = image is None or image.file_status != "available"
            source = record.get("source")
            source_referenced = False
            if source:
                variants = [source]
                try:
                    variants.append(Path(source).relative_to(Path(record.get("base_dir", settings.BASE_DIR)).resolve()).as_posix())
                except ValueError:
                    pass
                source_referenced = db.scalar(select(models.Image.image_id).where(
                    models.Image.file_path.in_(variants), models.Image.file_status == "available",
                ).limit(1)) is not None
                if not source_referenced:
                    source_referenced = db.scalar(select(models.PendingRequest.id).where(
                        models.PendingRequest.temp_file_path.in_(variants),
                        models.PendingRequest.status == models.RequestStatus.PENDING.value,
                    ).limit(1)) is not None
        if record["kind"] == "publish":
            if committed or referenced:
                if record.get("source_key"):
                    self._backend().delete(record["source_key"])
                elif source and not source_referenced and _signature(source) == record["source_signature"]:
                    Path(source).unlink(missing_ok=True)
            elif not referenced:
                self._backend().delete(record["key"])
        elif record["kind"] == "delete":
            if committed and not referenced:
                if locator and locator.startswith("r2://"):
                    self._backend().delete(locator.split("/", 3)[-1])
                elif source and not source_referenced and _signature(source) == record["source_signature"]:
                    Path(source).unlink(missing_ok=True)
                if derivatives_unused:
                    for path in record["derivatives"]:
                        Path(path).unlink(missing_ok=True)
        elif record["kind"] == "discard":
            if committed and source and not source_referenced and _signature(source) == record["source_signature"]:
                Path(source).unlink(missing_ok=True)
        else:
            raise ValueError("invalid_file_operation")
        # Remove intent before witness. A crash between these steps may leave a
        # harmless receipt, never a live intent that mistakes a commit for rollback.
        self.path.unlink(missing_ok=True)
        with Session(self.bind) as db:
            db.execute(delete(models.FileOperationReceipt).where(models.FileOperationReceipt.id == record["id"]))
            db.commit()

    def release(self):
        if self.handle is None:
            return
        self.handle.close()  # OS releases the advisory lease even on process exit.
        self.handle = None
        with _guard:
            _active.discard(str(self.path))
        if not self.path.exists():
            try:
                self.path.with_suffix(".lock").unlink(missing_ok=True)
            except OSError:
                pass


@event.listens_for(Session, "after_transaction_end")
def _finish_transaction_files(db, transaction):
    if transaction.parent is None:
        for operation in db.info.pop("file_operations", []):
            operation.finish()


def recover(db, limit=16):
    """Recover intents whose process/transaction no longer owns the OS lease."""
    bind = db.get_bind()
    directory = _directory(bind)
    completed = 0
    if not directory.exists():
        return completed
    attempted = 0
    for path in sorted(directory.glob("*.json")):
        if attempted >= limit:
            break
        handle = _lease(path)
        if handle is None:
            continue
        operation = None
        try:
            record = json.loads(path.read_text(encoding="utf-8"))
            if path.stem != record["id"]:
                raise ValueError("invalid_file_operation_id")
            operation = FileOperation(path, record, bind, handle)
            if record.get("retry_after", 0) > time.time():
                operation.release()
                continue
            attempted += 1
            completed += int(operation.finish())
        except Exception as error:
            log_error(f"File recovery deferred: type={type(error).__name__}")
            if operation is None:
                FileOperation(path, {}, bind, handle).release()
    return completed


class FileOperationWorker:
    """Independent recovery lane: remote cleanup must not block derivative jobs."""

    def __init__(self):
        self.stop_event = threading.Event()
        self.thread = None

    def run_once(self):
        from .database import SessionLocal
        with SessionLocal() as db:
            return recover(db)

    def _run(self):
        while not self.stop_event.is_set():
            try:
                self.run_once()
            except Exception as error:
                log_error(f"File recovery unavailable: type={type(error).__name__}")
            self.stop_event.wait(5)

    def start(self):
        if self.thread and self.thread.is_alive():
            return
        self.stop_event.clear()
        self.thread = threading.Thread(target=self._run, name="file_recovery_worker", daemon=True)
        self.thread.start()

    def stop(self, timeout=5):
        self.stop_event.set()
        if self.thread:
            self.thread.join(timeout=timeout)


file_operation_worker = FileOperationWorker()
