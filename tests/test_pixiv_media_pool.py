from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import threading
import time

import httpx
from PIL import Image
import pytest

from app.config import settings
from app.integrations.pixiv_ol import provider, media_pool, viewer


@pytest.fixture
def transport(monkeypatch):
    media_pool.media_clients.close()
    real_client = httpx.Client
    clients, options, requests = [], [], []
    handler = [lambda request: httpx.Response(200, content=b"image", headers={"Content-Type": "image/png"})]

    def respond(request):
        requests.append(request)
        return handler[0](request)

    def create(**kwargs):
        options.append(dict(kwargs))
        kwargs.pop("proxy", None)
        client = real_client(transport=httpx.MockTransport(respond), **kwargs)
        clients.append(client)
        return client

    monkeypatch.setattr(media_pool.httpx, "Client", create)
    monkeypatch.setattr(settings, "PIXIV_PROXY", "")
    monkeypatch.setattr(settings, "PIXIV_USE_SYSTEM_PROXY", False)
    monkeypatch.setattr(settings, "PIXIV_REQUEST_TIMEOUT_SECONDS", 5)
    monkeypatch.setattr(settings, "PIXIV_MEDIA_DOWNLOAD_WORKERS", 14)
    monkeypatch.setattr(settings, "PIXIV_MEDIA_PREVIEW_WORKERS", 8)
    yield clients, options, requests, handler
    media_pool.media_clients.close()


def test_reuses_connections_in_each_lane_and_never_sends_cdn_cookies(transport, tmp_path):
    clients, options, requests, handler = transport
    handler[0] = lambda request: httpx.Response(
        200, content=b"image", headers={"Content-Type": "image/png", "Set-Cookie": "cdn=tracking; Path=/"}
    )
    for index in range(2):
        provider.download("https://i.pximg.net/test.png", tmp_path / f"thumb-{index}", lane="preview")
    provider.download("https://i.pximg.net/test.png", tmp_path / "reader", lane="reader")
    assert len(clients) == 2 and not any(client.is_closed for client in clients)
    assert options[0]["limits"].max_connections == 8
    assert options[1]["limits"].max_connections == 2
    assert all(request.headers.get("cookie", "") == "" for request in requests)
    assert all("authorization" not in request.headers for request in requests)
    assert all(not value["trust_env"] and not value["follow_redirects"] for value in options)


def test_proxy_change_drains_active_client_then_closes_it(transport):
    clients, _, _, _ = transport
    started, release = threading.Event(), threading.Event()

    def old_request():
        with media_pool.media_clients.lease("reader", "http://first.test:7897", 5) as client:
            started.set()
            assert release.wait(3)
            assert not client.is_closed

    with ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(old_request)
        assert started.wait(3)
        with media_pool.media_clients.lease("reader", "http://second.test:7897", 5):
            assert len(clients) == 2
            assert not clients[0].is_closed
        release.set()
        future.result(3)
    assert clients[0].is_closed and not clients[1].is_closed


def test_original_queue_cannot_take_reader_slots_and_shutdown_preserves_waiters(transport):
    clients, _, _, _ = transport
    barrier, release, queued_entered = threading.Barrier(3), threading.Event(), threading.Event()

    def original(block):
        with media_pool.media_clients.lease("original", None, 5) as client:
            assert not client.is_closed
            if block:
                barrier.wait(3)
                assert release.wait(3)
            else:
                queued_entered.set()

    with ThreadPoolExecutor(max_workers=3) as executor:
        futures = [executor.submit(original, True) for _ in range(2)]
        barrier.wait(3)
        queued = executor.submit(original, False)
        deadline = time.monotonic() + 3
        while media_pool.media_clients.entries['original'].users != 3 and time.monotonic() < deadline:
            time.sleep(.005)
        assert media_pool.media_clients.entries['original'].users == 3
        assert not queued_entered.is_set()
        with media_pool.media_clients.lease("reader", None, 5):
            pass
        media_pool.media_clients.close()
        assert not clients[0].is_closed
        release.set()
        for future in futures + [queued]:
            future.result(3)
    assert queued_entered.is_set() and all(client.is_closed for client in clients)


def test_lane_wait_expires_without_leaking_a_slot(transport):
    barrier, release = threading.Barrier(3), threading.Event()

    def holder():
        with media_pool.media_clients.lease('original', None, .05):
            barrier.wait(3)
            assert release.wait(3)

    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [executor.submit(holder) for _ in range(2)]
        barrier.wait(3)
        try:
            with pytest.raises(httpx.PoolTimeout):
                with media_pool.media_clients.lease('original', None, .05):
                    pytest.fail('Third original request must not take another slot')
            entry = media_pool.media_clients.entries['original']
            assert entry.active == entry.users == 2
        finally:
            release.set()
        for future in futures:
            future.result(3)


@pytest.mark.parametrize('budget, previews', [(8, 12), (14, 8), (20, 100), (-1, -1)])
def test_total_download_budget_is_bounded_and_reader_has_reserved_capacity(monkeypatch, budget, previews):
    monkeypatch.setattr(settings, 'PIXIV_MEDIA_DOWNLOAD_WORKERS', budget)
    monkeypatch.setattr(settings, 'PIXIV_MEDIA_PREVIEW_WORKERS', previews)
    limits = media_pool.lane_limits()
    assert sum(limits.values()) <= max(8, min(20, budget))
    assert limits['reader'] == limits['original'] == limits['avatar'] == 2
    assert 1 <= limits['preview'] <= 12


@pytest.mark.parametrize('failure', ['redirect', 'oversized', 'wrong_type', 'transport'])
def test_pooled_download_keeps_redirect_size_type_checks_and_removes_partial_file(transport, tmp_path, failure):
    _, _, requests, handler = transport
    if failure == 'redirect':
        handler[0] = lambda request: httpx.Response(302, headers={'Location': 'https://evil.test/steal'})
        expected = 'untrusted_image_url'
    elif failure == 'oversized':
        expected = 'image_too_large'
    elif failure == 'wrong_type':
        handler[0] = lambda request: httpx.Response(200, content=b'error', headers={'Content-Type': 'text/html'})
        expected = 'invalid_image'
    else:
        def fail(request):
            raise httpx.ConnectError('redacted', request=request)
        handler[0] = fail
        expected = 'download_failed'
    destination = tmp_path / 'partial.img'
    destination.write_bytes(b'old partial')
    with pytest.raises(provider.PixivError) as raised:
        provider.download('https://i.pximg.net/test.png', destination, limit=1)
    assert raised.value.code == expected and not destination.exists()
    assert len(requests) == 1


def test_bad_initial_target_never_creates_a_connection(transport, tmp_path):
    clients, _, requests, _ = transport
    with pytest.raises(provider.PixivError) as raised:
        provider.download('http://127.0.0.1/private', tmp_path / 'bad')
    assert raised.value.code == 'untrusted_image_url'
    assert not clients and not requests


def test_cache_scans_once_and_failed_download_releases_reserved_space(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, 'TEMP_PATH', str(tmp_path))
    root = tmp_path / 'pixiv-ol-viewer'
    glob, scans = Path.glob, []

    def watched_glob(path, pattern, **kwargs):
        if path == root and pattern == '*/*.img':
            scans.append(path)
        return glob(path, pattern, **kwargs)

    def fetch(url, destination, **kwargs):
        assert kwargs['lane'] == 'reader'
        if url.endswith('fail.png'):
            raise provider.PixivError('download_failed')
        Image.new('RGB', (32, 20)).save(destination, format='PNG')

    monkeypatch.setattr(Path, 'glob', watched_glob)
    monkeypatch.setattr(viewer, 'download', fetch)
    for name in ['first', 'second']:
        viewer.cached_media('https://i.pximg.net/test.png', 'rev', name, 1024)
    with pytest.raises(provider.PixivError):
        viewer.cached_media('https://i.pximg.net/fail.png', 'rev', 'failed', 1024)
    assert len(scans) == 1
    assert viewer.CACHE_STATES[root]['reserved'] == 0
    assert viewer.CACHE_STATES[root]['used'] == sum(path.stat().st_size for path in root.glob('rev/*.img'))
    assert not list(root.glob('rev/*.part'))
