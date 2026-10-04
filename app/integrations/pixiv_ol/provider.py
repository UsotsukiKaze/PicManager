"""Bounded Pixiv App API adapter. Exceptions never include remote bodies or tokens."""

import os
import sys
import hashlib
from datetime import datetime, timezone
import threading
import time
from pathlib import Path
from urllib.parse import urlparse, parse_qs
from urllib.request import getproxies

import httpx
from cryptography.fernet import Fernet, InvalidToken
from pixivpy3 import AppPixivAPI

from ...config import settings
from ...logger import log_error


class PixivError(Exception):
    def __init__(self, code="external_error", delay=30):
        self.code = code
        self.delay = delay
        super().__init__(code)


def proxy_url():
    """Use one route for CLI OAuth, API refresh and CDN requests; never log proxy credentials."""
    value = settings.PIXIV_PROXY.strip()
    if not value and sys.platform == "win32" and settings.PIXIV_USE_SYSTEM_PROXY:
        try:
            proxies = getproxies()
        except OSError:
            proxies = {}
        value = proxies.get("https") or proxies.get("http") or proxies.get("all") or ""
    if not value:
        return None
    try:
        parsed = urlparse(value)
        if (
            parsed.scheme not in {"http", "https"}
            or not parsed.hostname
            or parsed.port == 0
            or parsed.path not in {"", "/"}
            or parsed.query
            or parsed.fragment
            or any(ord(char) <= 32 for char in value)
        ):
            raise ValueError()
    except ValueError:
        raise PixivError("pixiv_proxy_invalid") from None
    return value


_key_lock = threading.Lock()
_rate_lock = threading.Lock()
_last_request = 0.0


def cipher():
    with _key_lock:
        key = settings.PIXIV_OL_ENCRYPTION_KEY.strip()
        if not key:
            path = Path(settings.DATA_PATH) / ".pixiv_ol_key"
            path.parent.mkdir(parents=True, exist_ok=True)
            try:
                fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            except FileExistsError:
                pass
            else:
                with os.fdopen(fd, "wb") as output:
                    output.write(Fernet.generate_key())
            key = path.read_text(encoding="ascii").strip()
        try:
            return Fernet(key.encode("ascii"))
        except (ValueError, UnicodeError):
            raise PixivError("invalid_encryption_key") from None


def encrypt(token):
    return cipher().encrypt(token.encode()).decode()


def decrypt(value):
    try:
        return cipher().decrypt(value.encode()).decode()
    except InvalidToken:
        raise PixivError("invalid_encryption_key") from None


def plain(value):
    # pixivpy's JsonDict returns None for missing attributes, so hasattr is unsafe.
    if isinstance(value, dict):
        return value
    dump = getattr(value, "model_dump", None)
    if callable(dump):
        return dump(mode="json")
    return value


def throttle():
    global _last_request
    with _rate_lock:
        time.sleep(max(0, _last_request + max(0, settings.PIXIV_OL_REQUEST_INTERVAL) - time.monotonic()))
        _last_request = time.monotonic()


def login_response_error(response):
    """Classify rejected OAuth exchanges without exposing response text."""
    try:
        payload = response.json()
    except ValueError:
        payload = {}
    if not isinstance(payload, dict):
        payload = {}
    oauth_error = payload.get("error")
    remote_errors = payload.get("errors")
    system = remote_errors.get("system") if isinstance(remote_errors, dict) else None
    remote_code = system.get("code") if isinstance(system, dict) else None
    remote_code = remote_code if type(remote_code) is int and 0 <= remote_code <= 999999 else None
    if response.status_code >= 500:
        error = "login_service_unavailable"
    elif oauth_error in ("invalid_client", "unauthorized_client"):
        error = "login_client_rejected"
    elif oauth_error == "invalid_grant":
        error = "login_exchange_failed"
    else:
        error = "login_authorization_rejected"
    log_error(f"Pixiv OAuth rejected: http_status={response.status_code}, error={error}, remote_code={remote_code}")
    return error


class BoundedAPI(AppPixivAPI):
    def __init__(self, **options):
        super().__init__(**options)
        # The route is resolved explicitly above, rather than differently by each HTTP library.
        self.requests.trust_env = False

    def auth(self, username=None, password=None, refresh_token=None, headers=None):
        """Parse both OAuth envelopes before exposing credentials to pixivpy API methods."""
        token = refresh_token or self.refresh_token
        if username or password or not isinstance(token, str) or not token:
            raise PixivError("reauth_required")
        stamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S+00:00")
        response = self.requests_call(
            "POST",
            "https://oauth.secure.pixiv.net/auth/token",
            headers={
                **(headers or {}),
                "User-Agent": "PixivAndroidApp/5.0.234 (Android 11; Pixel 5)",
                "X-Client-Time": stamp,
                "X-Client-Hash": hashlib.md5((stamp + self.hash_secret).encode()).hexdigest(),
            },
            data={
                "client_id": self.client_id,
                "client_secret": self.client_secret,
                "grant_type": "refresh_token",
                "refresh_token": token,
                "include_policy": "true",
            },
        )
        try:
            data = response.json()
            payload = data.get("response", data) if isinstance(data, dict) else None
            user = payload.get("user") if isinstance(payload, dict) else None
            access = payload.get("access_token") if isinstance(payload, dict) else None
            rotated = payload.get("refresh_token") if isinstance(payload, dict) else None
            if (
                not isinstance(user, dict)
                or not str(user.get("id", "")).isdigit()
                or int(user["id"]) <= 0
                or not isinstance(access, str)
                or not access
                or len(access) > 8192
                or any(char.isspace() for char in access)
                or not isinstance(rotated, str)
                or not 20 <= len(rotated) <= 4096
                or any(char.isspace() for char in rotated)
            ):
                raise ValueError()
        except (ValueError, TypeError, AttributeError):
            raise PixivError("login_response_invalid") from None
        self.user_id = int(user["id"])
        self.access_token, self.refresh_token = access, rotated
        return {"response": payload}

    def requests_call(self, method, url, *args, **kwargs):
        parsed = urlparse(url)
        if parsed.scheme != "https" or parsed.hostname not in {"app-api.pixiv.net", "oauth.secure.pixiv.net"}:
            raise PixivError("untrusted_api_url")
        data = kwargs.get("data")
        login_exchange = (
            method == "POST"
            and parsed.hostname == "oauth.secure.pixiv.net"
            and parsed.path == "/auth/token"
            and isinstance(data, dict)
            and data.get("grant_type") == "authorization_code"
        )
        refresh_exchange = (
            method == "POST"
            and parsed.hostname == "oauth.secure.pixiv.net"
            and parsed.path == "/auth/token"
            and isinstance(data, dict)
            and data.get("grant_type") == "refresh_token"
        )
        try:
            response = super().requests_call(method, url, *args, **kwargs)
        except Exception:
            if login_exchange or refresh_exchange:
                raise PixivError("login_network_error") from None
            raise
        if response.status_code == 429:
            try:
                delay = max(5, min(3600, int(response.headers.get("Retry-After", "60"))))
            except ValueError:
                delay = 60
            raise PixivError("rate_limited", delay)
        if login_exchange and response.status_code >= 300:
            if response.status_code == 403:
                raise PixivError("access_denied")
            raise PixivError(login_response_error(response))
        if refresh_exchange and response.status_code == 400:
            try:
                payload = response.json()
            except ValueError:
                payload = {}
            error = payload.get("error") if isinstance(payload, dict) else None
            if error == "invalid_grant":
                raise PixivError("reauth_required")
            if error in ("invalid_client", "unauthorized_client"):
                raise PixivError("login_client_rejected")
            raise PixivError("external_error")
        if response.status_code == 401:
            raise PixivError("reauth_required")
        if response.status_code == 403:
            raise PixivError("access_denied")
        if response.status_code == 404 and method == "GET" and parsed.path == "/v1/illust/detail":
            raise PixivError("artwork_unavailable")
        if response.status_code >= 300:
            raise PixivError("external_error")
        return response


class Provider:
    def __init__(self, token):
        options = {"timeout": max(5, settings.PIXIV_REQUEST_TIMEOUT_SECONDS), "allow_redirects": False}
        proxy = proxy_url()
        if proxy:
            options["proxies"] = {"http": proxy, "https": proxy}
        self.api = BoundedAPI(**options)
        try:
            throttle()
            response = plain(self.api.auth(refresh_token=token))
            self.token = str(self.api.refresh_token or token)
            response = response.get("response", response)
            user = response.get("user", {})
            self.user = {"id": str(user.get("id", "")), "name": str(user.get("name", ""))}
            if not self.user["id"].isdigit():
                raise ValueError()
        except PixivError:
            self.close()
            raise
        except Exception:
            self.close()
            raise PixivError("external_error") from None

    def close(self):
        session = getattr(self.api, "requests", None)
        if hasattr(session, "close"):
            session.close()

    def call(self, method, **kwargs):
        try:
            throttle()
            response = plain(getattr(self.api, method)(**kwargs))
        except PixivError:
            raise
        except Exception:
            raise PixivError("external_error") from None
        if not isinstance(response, dict) or response.get("error"):
            raise PixivError("external_error")
        return response

    @staticmethod
    def cursor(next_url):
        if not next_url:
            return None
        parsed = urlparse(next_url)
        if parsed.scheme != "https" or parsed.hostname != "app-api.pixiv.net":
            raise PixivError("invalid_cursor")
        allowed = {"offset", "max_bookmark_id_for_recommend", "min_bookmark_id_for_recent_illust", "seed_illust_ids"}
        return {key: value[-1] for key, value in parse_qs(parsed.query).items() if key in allowed}


def trusted_image_url(url):
    try:
        parsed = urlparse(url)
        return (
            parsed.scheme == "https"
            and parsed.hostname == "i.pximg.net"
            and parsed.port in (None, 443)
            and not parsed.username
            and not parsed.password
        )
    except ValueError:
        return False


def download(url, destination, *, limit=None):
    """CDN requests have no Pixiv account credentials; validate every redirect."""
    limit = limit or min(settings.MAX_FILE_SIZE, settings.PIXIV_MAX_DOWNLOAD_BYTES)
    options = {"timeout": max(5, settings.PIXIV_REQUEST_TIMEOUT_SECONDS), "follow_redirects": False, "trust_env": False}
    proxy = proxy_url()
    if proxy:
        options["proxy"] = proxy
    try:
        with httpx.Client(**options) as client:
            for _ in range(4):
                if not trusted_image_url(url):
                    raise PixivError("untrusted_image_url")
                with client.stream("GET", url, headers={"Referer": "https://www.pixiv.net/"}) as response:
                    if response.is_redirect:
                        url = str(response.url.join(response.headers.get("location", "")))
                        continue
                    response.raise_for_status()
                    if not response.headers.get("content-type", "").lower().startswith("image/"):
                        raise PixivError("invalid_image")
                    written = 0
                    with Path(destination).open("wb") as output:
                        for chunk in response.iter_bytes(65536):
                            written += len(chunk)
                            if written > limit:
                                raise PixivError("image_too_large")
                            output.write(chunk)
                    return
        raise PixivError("too_many_redirects")
    except PixivError:
        Path(destination).unlink(missing_ok=True)
        raise
    except Exception:
        Path(destination).unlink(missing_ok=True)
        raise PixivError("download_failed") from None
