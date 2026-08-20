"""Local performance diagnostics for PicManager storage and network placement."""

from __future__ import annotations

import os
import shutil
import socket
import tempfile
import time
from pathlib import Path
from typing import Any, Iterable


def _throughput_mbps(byte_count: int, elapsed: float) -> float:
    return round((byte_count / (1024 * 1024)) / max(elapsed, 0.000001), 2)


def benchmark_directory(path: str | Path, size_mb: int = 16) -> dict[str, Any]:
    """Measure sequential write/read throughput with a bounded temporary file."""
    target = Path(path).resolve()
    target.mkdir(parents=True, exist_ok=True)
    byte_count = max(1, int(size_mb)) * 1024 * 1024
    block = b"\0" * min(byte_count, 1024 * 1024)
    temp_path: Path | None = None

    try:
        descriptor, raw_path = tempfile.mkstemp(prefix=".picmanager-bench-", dir=target)
        temp_path = Path(raw_path)
        write_started = time.perf_counter()
        with os.fdopen(descriptor, "wb", closefd=True) as stream:
            remaining = byte_count
            while remaining:
                chunk = block[: min(len(block), remaining)]
                stream.write(chunk)
                remaining -= len(chunk)
            stream.flush()
            os.fsync(stream.fileno())
        write_seconds = time.perf_counter() - write_started

        read_started = time.perf_counter()
        with temp_path.open("rb") as stream:
            while stream.read(1024 * 1024):
                pass
        read_seconds = time.perf_counter() - read_started
        usage = shutil.disk_usage(target)
        return {
            "path": str(target),
            "sample_mb": max(1, int(size_mb)),
            "write_mib_s": _throughput_mbps(byte_count, write_seconds),
            "read_mib_s": _throughput_mbps(byte_count, read_seconds),
            "free_gib": round(usage.free / (1024**3), 2),
            "ok": True,
        }
    except OSError as exc:
        return {"path": str(target), "ok": False, "error": str(exc)}
    finally:
        if temp_path is not None:
            temp_path.unlink(missing_ok=True)


def network_summary() -> dict[str, Any]:
    """Report local addresses; actual Internet upload speed needs an external endpoint."""
    hostname = socket.gethostname()
    addresses: set[str] = set()
    try:
        for result in socket.getaddrinfo(hostname, None):
            address = result[4][0]
            if address not in {"127.0.0.1", "::1"}:
                addresses.add(address)
    except OSError:
        pass
    return {
        "hostname": hostname,
        "addresses": sorted(addresses),
        "external_speed_tested": False,
        "note": "Wi-Fi link rate is not Internet upload throughput; verify origin uplink and Cloudflare path separately.",
    }


def diagnose(paths: Iterable[str | Path], size_mb: int = 16) -> dict[str, Any]:
    storage = [benchmark_directory(path, size_mb=size_mb) for path in paths]
    warnings: list[str] = []
    for result in storage:
        if not result.get("ok"):
            warnings.append(f"Storage benchmark failed: {result['path']}")
        elif result["write_mib_s"] < 20:
            warnings.append(f"Slow sequential writes detected: {result['path']}")
        if result.get("free_gib", 1) < 1:
            warnings.append(f"Less than 1 GiB free: {result['path']}")
    return {"storage": storage, "network": network_summary(), "warnings": warnings}
