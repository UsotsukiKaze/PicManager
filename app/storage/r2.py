"""Cloudflare R2 backend through its S3-compatible API."""

from __future__ import annotations

from pathlib import Path

from .base import StoredObject, normalize_key


class R2Storage:
    def __init__(
        self,
        *,
        account_id: str,
        bucket: str,
        access_key_id: str,
        secret_access_key: str,
        prefix: str = "images",
        client=None,
    ):
        if not account_id or not bucket or not access_key_id or not secret_access_key:
            raise ValueError("R2 storage requires account, bucket, access key and secret")
        self.bucket = bucket
        self.prefix = normalize_key(prefix) if prefix else ""
        if client is None:
            try:
                import boto3
            except ImportError as exc:
                raise RuntimeError("Install boto3>=1.35 to use R2 storage") from exc
            client = boto3.client(
                "s3",
                endpoint_url=f"https://{account_id}.r2.cloudflarestorage.com",
                aws_access_key_id=access_key_id,
                aws_secret_access_key=secret_access_key,
                region_name="auto",
            )
        self.client = client

    def _key(self, key: str) -> str:
        normalized = normalize_key(key)
        if self.prefix and normalized.startswith(f"{self.prefix}/"):
            return normalized
        return f"{self.prefix}/{normalized}" if self.prefix else normalized

    def put_file(self, source: str | Path, key: str, *, move: bool = False) -> StoredObject:
        source_path = Path(source).resolve()
        object_key = self._key(key)
        self.client.upload_file(str(source_path), self.bucket, object_key)
        size = source_path.stat().st_size
        if move:
            source_path.unlink()
        return StoredObject(object_key, f"r2://{self.bucket}/{object_key}", size)

    def exists(self, key: str) -> bool:
        try:
            self.client.head_object(Bucket=self.bucket, Key=self._key(key))
            return True
        except Exception:
            return False

    def delete(self, key: str) -> None:
        self.client.delete_object(Bucket=self.bucket, Key=self._key(key))

    def local_path(self, key: str) -> None:
        return None

    def signed_download_url(self, key: str, *, expires: int = 300) -> str:
        return self.client.generate_presigned_url(
            "get_object",
            Params={"Bucket": self.bucket, "Key": self._key(key)},
            ExpiresIn=max(1, int(expires)),
        )
