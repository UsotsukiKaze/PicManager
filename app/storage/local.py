"""Local filesystem storage backend."""

from __future__ import annotations

import errno
import os
import shutil
from pathlib import Path

from .base import StoredObject, normalize_key


class LocalStorage:
    def __init__(self, root: str | Path, *, base_dir: str | Path | None = None):
        self.root = Path(root).resolve()
        self.base_dir = Path(base_dir).resolve() if base_dir else self.root.parent

    def _path(self, key: str) -> Path:
        target = (self.root / normalize_key(key)).resolve()
        target.relative_to(self.root)
        return target

    def _locator(self, target: Path) -> str:
        try:
            return target.relative_to(self.base_dir).as_posix()
        except ValueError:
            return str(target)

    def put_file(self, source: str | Path, key: str, *, move: bool = False) -> StoredObject:
        source_path = Path(source).resolve()
        target = self._path(key)
        target.parent.mkdir(parents=True, exist_ok=True)
        if source_path != target:
            if move:
                try:
                    os.replace(source_path, target)
                except OSError as exc:
                    if exc.errno != errno.EXDEV:
                        raise
                    shutil.copy2(source_path, target)
                    source_path.unlink()
            else:
                shutil.copy2(source_path, target)
        return StoredObject(normalize_key(key), self._locator(target), target.stat().st_size)

    def exists(self, key: str) -> bool:
        return self._path(key).is_file()

    def delete(self, key: str) -> None:
        self._path(key).unlink(missing_ok=True)

    def local_path(self, key: str) -> Path:
        return self._path(key)

    def download_file(self, key: str, target: str | Path) -> None:
        shutil.copy2(self._path(key), Path(target))

    def move_object(self, source_key: str, target_key: str) -> StoredObject:
        return self.put_file(self._path(source_key), target_key, move=True)

    def presigned_upload_url(self, key: str, *, content_type: str, expires: int = 900) -> None:
        return None

    def signed_download_url(self, key: str, *, expires: int = 300, download_name: str | None = None) -> None:
        return None
