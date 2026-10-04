"""Bounded, credential-free CDN connection pools with reserved media lanes."""

import atexit
import threading
import time
from contextlib import contextmanager
from dataclasses import dataclass

import httpx

from ...config import settings


def lane_limits():
    # The sum is bounded by the configured budget; small media cannot take the
    # two slots reserved for reading, avatars, or original-file downloads.
    budget = max(8, min(20, settings.PIXIV_MEDIA_DOWNLOAD_WORKERS))
    previews = max(1, min(12, settings.PIXIV_MEDIA_PREVIEW_WORKERS, budget - 6))
    return {"preview": previews, "reader": 2, "avatar": 2, "original": 2}


@dataclass
class Entry:
    client: httpx.Client
    limit: int
    users: int = 0
    active: int = 0
    retired: bool = False


class MediaClients:
    def __init__(self):
        self.condition = threading.Condition()
        self.entries = {}
        self.signature = None

    def _retire(self):
        for entry in self.entries.values():
            entry.retired = True
            if not entry.users:
                entry.client.close()
        self.entries = {}

    @contextmanager
    def lease(self, lane, proxy, timeout):
        limits = lane_limits()
        if lane not in limits:
            raise ValueError("invalid_media_lane")
        signature = (proxy, timeout, tuple(limits.items()))
        with self.condition:
            if signature != self.signature:
                self._retire()
                self.signature = signature
            entry = self.entries.get(lane)
            if entry is None:
                client = httpx.Client(
                    proxy=proxy,
                    trust_env=False,
                    follow_redirects=False,
                    timeout=httpx.Timeout(timeout, connect=min(8, timeout)),
                    limits=httpx.Limits(
                        max_connections=limits[lane],
                        max_keepalive_connections=limits[lane],
                        keepalive_expiry=30,
                    ),
                )
                entry = self.entries[lane] = Entry(client, limits[lane])
            # Count waiters as users so proxy changes / shutdown cannot close a
            # client underneath a request that is already waiting for its lane.
            entry.users += 1
            try:
                deadline = time.monotonic() + min(8, timeout)
                while entry.active >= entry.limit:
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        raise httpx.PoolTimeout("media_lane_busy")
                    self.condition.wait(remaining)
                entry.active += 1
            except BaseException:
                entry.users -= 1
                if entry.retired and not entry.users:
                    entry.client.close()
                raise
        try:
            yield entry.client
        finally:
            with self.condition:
                entry.active -= 1
                entry.users -= 1
                self.condition.notify_all()
                if entry.retired and not entry.users:
                    entry.client.close()

    def close(self):
        with self.condition:
            self._retire()
            self.signature = None


media_clients = MediaClients()
atexit.register(media_clients.close)
