"""Pixiv-backed, administrator-reviewed original image upgrades."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import re
import shutil
import threading
import time
import uuid
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse

import httpx
from PIL import Image as PILImage
from sqlalchemy.orm import Session

from . import models
from .config import settings


class PixivLookupError(RuntimeError):
    """A temporary lookup/download failure that must not mark an image checked."""


@dataclass
class PixivCandidate:
    staged_path: Path
    filename: str
    width: int
    height: int
    file_size: int
    page_index: int
    source_url: str
    distance: int


class PixivClient:
    API_URL = "https://www.pixiv.net/ajax/illust/{pid}/pages?lang=zh"
    ARTWORK_URL = "https://www.pixiv.net/artworks/{pid}"
    USER_AGENT = (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126 Safari/537.36"
    )

    def __init__(self) -> None:
        headers = {
            "Accept": "application/json,text/plain,*/*",
            "Referer": "https://www.pixiv.net/",
            "User-Agent": self.USER_AGENT,
        }
        if settings.PIXIV_COOKIE.strip():
            headers["Cookie"] = settings.PIXIV_COOKIE.strip()
        self.client = httpx.Client(
            headers=headers,
            follow_redirects=True,
            timeout=max(5, settings.PIXIV_REQUEST_TIMEOUT_SECONDS),
        )

    def close(self) -> None:
        self.client.close()

    @staticmethod
    def _trusted_image_url(url: str) -> bool:
        parsed = urlparse(url)
        host = (parsed.hostname or "").lower()
        return parsed.scheme == "https" and (host == "pximg.net" or host.endswith(".pximg.net"))

    def pages(self, pid: str) -> list[dict]:
        try:
            response = self.client.get(self.API_URL.format(pid=pid))
        except httpx.HTTPError as exc:
            raise PixivLookupError(f"Pixiv 连接失败: {exc}") from exc
        if response.status_code == 404:
            return []
        if response.status_code in {401, 403, 429}:
            raise PixivLookupError(f"Pixiv 拒绝了请求 (HTTP {response.status_code})")
        if response.status_code >= 500:
            raise PixivLookupError(f"Pixiv 服务暂时异常 (HTTP {response.status_code})")
        try:
            response.raise_for_status()
            payload = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise PixivLookupError("Pixiv 返回了无效数据") from exc
        if payload.get("error"):
            # Deleted, private, or otherwise unavailable artwork is a completed lookup.
            return []
        body = payload.get("body")
        return body if isinstance(body, list) else []

    def download(self, url: str, destination: Path) -> tuple[int, int, int]:
        if not self._trusted_image_url(url):
            raise PixivLookupError("Pixiv 返回了不可信的图片地址")
        destination.parent.mkdir(parents=True, exist_ok=True)
        written = 0
        try:
            with self.client.stream("GET", url, headers={"Referer": "https://www.pixiv.net/"}) as response:
                if response.status_code in {401, 403, 429} or response.status_code >= 500:
                    raise PixivLookupError(f"Pixiv 原图下载失败 (HTTP {response.status_code})")
                response.raise_for_status()
                content_type = response.headers.get("content-type", "").lower()
                if content_type and not content_type.startswith("image/"):
                    raise PixivLookupError("Pixiv 原图响应不是图片")
                with destination.open("wb") as output:
                    for chunk in response.iter_bytes(1024 * 256):
                        written += len(chunk)
                        if written > settings.PIXIV_MAX_DOWNLOAD_BYTES:
                            raise PixivLookupError("Pixiv 原图超过下载大小限制")
                        output.write(chunk)
            with PILImage.open(destination) as image:
                image.verify()
            with PILImage.open(destination) as image:
                width, height = image.size
            return int(width), int(height), written
        except PixivLookupError:
            destination.unlink(missing_ok=True)
            raise
        except (httpx.HTTPError, OSError, ValueError) as exc:
            destination.unlink(missing_ok=True)
            raise PixivLookupError(f"Pixiv 原图下载失败: {exc}") from exc


class PixivUpgradeService:
    STAGED_PREFIX = "pixiv-upgrade-"
    _ASCII_PID = re.compile(r"^[0-9]+$")
    LOCK = threading.Lock()

    @staticmethod
    def _image_dimensions(image: models.Image) -> tuple[int, int]:
        from .services import ImageService

        width, height = int(image.width or 0), int(image.height or 0)
        if width > 0 and height > 0:
            return width, height
        with PILImage.open(ImageService.image_full_path(image)) as source:
            return int(source.width), int(source.height)

    @staticmethod
    def _extension(url: str) -> str:
        extension = Path(urlparse(url).path).suffix.lower().lstrip(".")
        if extension == "jpeg":
            extension = "jpg"
        if extension not in {"jpg", "png", "webp", "gif"}:
            raise PixivLookupError("不支持 Pixiv 原图的文件格式")
        return extension

    @staticmethod
    def cleanup_staged() -> None:
        root = Path(settings.PENDING_PATH)
        if not root.is_dir():
            return
        cutoff = time.time() - max(300, settings.PIXIV_UPGRADE_TOKEN_TTL_SECONDS)
        for path in root.glob(f"{PixivUpgradeService.STAGED_PREFIX}*"):
            try:
                if path.is_file() and path.stat().st_mtime < cutoff:
                    path.unlink()
            except OSError:
                pass

    @staticmethod
    def find_candidate(image: models.Image, client: PixivClient | None = None) -> PixivCandidate | None:
        from .services import ImageService

        client = client or PixivClient()
        pid = str(image.pid or "")
        pages = client.pages(pid)
        if not pages:
            return None

        current_path = Path(ImageService.image_full_path(image))
        current_width, current_height = PixivUpgradeService._image_dimensions(image)
        current_area = current_width * current_height
        current_hash = ImageService.compute_dhash(str(current_path))
        best: tuple[int, int, str] | None = None
        root = Path(settings.PENDING_PATH)
        root.mkdir(parents=True, exist_ok=True)

        for page_index, page in enumerate(pages):
            urls = page.get("urls") if isinstance(page, dict) else None
            if not isinstance(urls, dict):
                continue
            original_url = str(urls.get("original") or "")
            sample_url = str(urls.get("regular") or urls.get("small") or original_url)
            try:
                remote_width = int(page.get("width") or 0)
                remote_height = int(page.get("height") or 0)
            except (TypeError, ValueError):
                continue
            remote_area = remote_width * remote_height
            if (
                not original_url
                or remote_area <= current_area
                or remote_width < current_width
                or remote_height < current_height
            ):
                continue

            sample_path = root / f".{PixivUpgradeService.STAGED_PREFIX}{uuid.uuid4().hex}.sample"
            try:
                client.download(sample_url, sample_path)
                distance = ImageService.dhash_distance(current_hash, ImageService.compute_dhash(str(sample_path)))
            finally:
                sample_path.unlink(missing_ok=True)
            if distance <= settings.PIXIV_UPGRADE_DHASH_DISTANCE and (best is None or distance < best[0]):
                best = (distance, page_index, original_url)

        if best is None:
            return None

        distance, page_index, original_url = best
        extension = PixivUpgradeService._extension(original_url)
        filename = f"{PixivUpgradeService.STAGED_PREFIX}{uuid.uuid4().hex}.{extension}"
        staged_path = root / filename
        width, height, file_size = client.download(original_url, staged_path)
        if width < current_width or height < current_height or width * height <= current_area:
            staged_path.unlink(missing_ok=True)
            return None
        return PixivCandidate(
            staged_path=staged_path,
            filename=filename,
            width=width,
            height=height,
            file_size=file_size,
            page_index=page_index,
            source_url=original_url,
            distance=distance,
        )

    @staticmethod
    def pending_images(db: Session) -> list[models.Image]:
        from .services import ImageService

        candidates = db.query(models.Image).filter(
            models.Image.pixiv_checked_at.is_(None),
            models.Image.file_status == ImageService.AVAILABLE,
            models.Image.pid.isnot(None),
        ).order_by(models.Image.created_at.asc(), models.Image.image_id.asc()).all()
        return [
            image for image in candidates
            if PixivUpgradeService._ASCII_PID.fullmatch(str(image.pid or ""))
            and ImageService.image_file_exists(image)
        ]

    @staticmethod
    def next_image(db: Session) -> models.Image | None:
        candidates = PixivUpgradeService.pending_images(db)
        return candidates[0] if candidates else None

    @staticmethod
    def _b64encode(value: bytes) -> str:
        return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")

    @staticmethod
    def _b64decode(value: str) -> bytes:
        return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))

    @staticmethod
    def make_token(image: models.Image, candidate: PixivCandidate) -> str:
        from .services import ImageService

        current_stat = Path(ImageService.image_full_path(image)).stat()
        payload = {
            "image_id": image.image_id,
            "pid": str(image.pid),
            "filename": candidate.filename,
            "width": candidate.width,
            "height": candidate.height,
            "file_size": candidate.file_size,
            "page_index": candidate.page_index,
            "source_url": candidate.source_url,
            "current_size": current_stat.st_size,
            "current_mtime_ns": current_stat.st_mtime_ns,
            "expires_at": int(time.time()) + max(300, settings.PIXIV_UPGRADE_TOKEN_TTL_SECONDS),
        }
        encoded = PixivUpgradeService._b64encode(json.dumps(payload, separators=(",", ":")).encode("utf-8"))
        signature = hmac.new(settings.SECRET_KEY.encode("utf-8"), encoded.encode("ascii"), hashlib.sha256).digest()
        return f"{encoded}.{PixivUpgradeService._b64encode(signature)}"

    @staticmethod
    def decode_token(token: str) -> dict:
        try:
            encoded, supplied = token.split(".", 1)
            expected = hmac.new(settings.SECRET_KEY.encode("utf-8"), encoded.encode("ascii"), hashlib.sha256).digest()
            if not hmac.compare_digest(expected, PixivUpgradeService._b64decode(supplied)):
                raise ValueError
            payload = json.loads(PixivUpgradeService._b64decode(encoded))
            if int(payload.get("expires_at") or 0) < int(time.time()):
                raise ValueError
            filename = str(payload.get("filename") or "")
            if not re.fullmatch(r"pixiv-upgrade-[0-9a-f]{32}\.(jpg|png|webp|gif)", filename):
                raise ValueError
            return payload
        except (TypeError, ValueError, KeyError, json.JSONDecodeError) as exc:
            raise ValueError("Pixiv 候选图已失效，请重新扫描") from exc

    @staticmethod
    def scan_next(db: Session) -> dict:
        from .services import ImageService

        PixivUpgradeService.cleanup_staged()
        pending_images = PixivUpgradeService.pending_images(db)
        remaining_before = len(pending_images)
        image = pending_images[0] if pending_images else None
        if image is None:
            return {"status": "complete", "remaining": 0}
        client = PixivClient()
        try:
            candidate = PixivUpgradeService.find_candidate(image, client)
        finally:
            client.close()
        if candidate is None:
            image.pixiv_checked_at = datetime.utcnow()
            return {
                "status": "checked",
                "image_id": image.image_id,
                "pid": image.pid,
                "remaining": remaining_before - 1,
            }
        token = PixivUpgradeService.make_token(image, candidate)
        current_width, current_height = PixivUpgradeService._image_dimensions(image)
        return {
            "status": "candidate",
            "remaining": remaining_before,
            "token": token,
            "artwork_url": PixivClient.ARTWORK_URL.format(pid=image.pid),
            "current": {
                "image_id": image.image_id,
                "pid": image.pid,
                "preview_url": f"/resource/originals/{image.image_id}?v={int(time.time())}",
                "width": current_width,
                "height": current_height,
                "file_size": image.file_size or Path(ImageService.image_full_path(image)).stat().st_size,
            },
            "candidate": {
                "preview_url": f"/resource/pending/{candidate.filename}",
                "width": candidate.width,
                "height": candidate.height,
                "file_size": candidate.file_size,
                "page_index": candidate.page_index,
                "distance": candidate.distance,
            },
        }

    @staticmethod
    def resolve(db: Session, token: str, action: str) -> dict:
        from .services import ImageService

        payload = PixivUpgradeService.decode_token(token)
        image = db.query(models.Image).filter(models.Image.image_id == payload["image_id"]).first()
        if not image or str(image.pid or "") != str(payload.get("pid") or ""):
            raise ValueError("图片或 PID 已变更，请重新扫描")
        if image.pixiv_checked_at is not None:
            raise ValueError("这张图已经检查过")
        staged = (Path(settings.PENDING_PATH).resolve() / payload["filename"]).resolve()
        staged.relative_to(Path(settings.PENDING_PATH).resolve())
        if not staged.is_file():
            raise ValueError("Pixiv 候选图已失效，请重新扫描")

        current_path = Path(ImageService.image_full_path(image)).resolve()
        if not current_path.is_file():
            raise ValueError("当前原图已不存在")
        current_stat = current_path.stat()
        if (
            current_stat.st_size != int(payload.get("current_size") or -1)
            or current_stat.st_mtime_ns != int(payload.get("current_mtime_ns") or -1)
        ):
            raise ValueError("当前原图已变更，请重新扫描")

        if action == "skip":
            staged.unlink(missing_ok=True)
            image.pixiv_checked_at = datetime.utcnow()
            return {"status": "skipped", "image_id": image.image_id}
        if action != "replace":
            raise ValueError("无效的 Pixiv 处理选项")

        extension = staged.suffix.lower().lstrip(".")
        old_path = current_path
        target = (Path(settings.STORE_PATH).resolve() / f"{image.image_id}.{extension}").resolve()
        target.relative_to(Path(settings.STORE_PATH).resolve())
        if target != old_path and target.exists():
            raise ValueError("目标文件名已被占用，请先整理孤立文件")

        try:
            with PILImage.open(staged) as source:
                candidate_width, candidate_height = source.size
        except (OSError, ValueError) as exc:
            raise ValueError("Pixiv 候选图已损坏，请重新扫描") from exc
        current_width, current_height = PixivUpgradeService._image_dimensions(image)
        if (
            candidate_width < current_width
            or candidate_height < current_height
            or candidate_width * candidate_height <= current_width * current_height
        ):
            raise ValueError("Pixiv 候选图不再比当前原图清晰")

        backup = Path(settings.PENDING_PATH) / f".pixiv-backup-{uuid.uuid4().hex}{old_path.suffix}"
        shutil.copy2(old_path, backup)
        try:
            os.replace(staged, target)
            try:
                image.file_path = target.relative_to(Path(settings.BASE_DIR).resolve()).as_posix()
            except ValueError:
                image.file_path = str(target)
            image.file_extension = extension
            image.file_size = target.stat().st_size
            with PILImage.open(target) as source:
                image.width, image.height = source.size
            image.original_filename = Path(urlparse(str(payload.get("source_url") or "")).path).name or target.name
            image.perceptual_hash = ImageService.compute_dhash(str(target))
            image.file_status = ImageService.AVAILABLE
            image.file_checked_at = datetime.utcnow()
            image.pixiv_checked_at = datetime.utcnow()
            thumb = Path(ImageService.thumb_path(image))
            thumb.unlink(missing_ok=True)
            ImageService.ensure_thumbnail(image)
            db.commit()
        except Exception:
            db.rollback()
            if target != old_path:
                target.unlink(missing_ok=True)
            os.replace(backup, old_path)
            raise
        try:
            backup.unlink(missing_ok=True)
            if old_path != target:
                old_path.unlink(missing_ok=True)
        except OSError:
            # The replacement is already committed; stale cleanup can be handled
            # by the existing orphan-file maintenance operation.
            pass
        return {
            "status": "replaced",
            "image_id": image.image_id,
            "width": image.width,
            "height": image.height,
        }
