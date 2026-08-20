"""Configured storage backend factory."""

from __future__ import annotations

from pathlib import Path

from .base import StorageBackend, StoredObject
from .local import LocalStorage
from .r2 import R2Storage


def get_image_storage(settings, *, local_root: str | Path | None = None) -> StorageBackend:
    backend = str(settings.STORAGE_BACKEND or "local").strip().lower()
    if backend == "local":
        return LocalStorage(local_root or settings.STORE_PATH, base_dir=settings.BASE_DIR)
    if backend == "r2":
        return R2Storage(
            account_id=settings.R2_ACCOUNT_ID,
            bucket=settings.R2_BUCKET,
            access_key_id=settings.R2_ACCESS_KEY_ID,
            secret_access_key=settings.R2_SECRET_ACCESS_KEY,
            prefix=settings.R2_PREFIX,
        )
    raise ValueError(f"Unsupported STORAGE_BACKEND: {backend}")


__all__ = ["StorageBackend", "StoredObject", "LocalStorage", "R2Storage", "get_image_storage"]
