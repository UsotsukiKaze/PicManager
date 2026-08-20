"""Storage contracts used by image services and delivery routes."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Protocol, runtime_checkable


@dataclass(frozen=True)
class StoredObject:
    key: str
    locator: str
    size: int


def normalize_key(key: str) -> str:
    normalized = str(PurePosixPath(str(key).replace("\\", "/"))).lstrip("/")
    if not normalized or normalized == "." or ".." in PurePosixPath(normalized).parts:
        raise ValueError("Invalid storage key")
    return normalized


@runtime_checkable
class StorageBackend(Protocol):
    def put_file(self, source: str | Path, key: str, *, move: bool = False) -> StoredObject: ...
    def exists(self, key: str) -> bool: ...
    def delete(self, key: str) -> None: ...
    def local_path(self, key: str) -> Path | None: ...
    def download_file(self, key: str, target: str | Path) -> None: ...
    def move_object(self, source_key: str, target_key: str) -> StoredObject: ...
    def presigned_upload_url(self, key: str, *, content_type: str, expires: int = 900) -> str | None: ...
    def signed_download_url(self, key: str, *, expires: int = 300, download_name: str | None = None) -> str | None: ...
