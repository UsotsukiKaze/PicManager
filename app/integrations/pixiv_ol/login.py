"""Pixiv's own App OAuth page with PKCE and an optional local browser helper."""

import base64
import hashlib
import os
import re
import secrets
import sys
import threading
from datetime import datetime, timedelta
from ipaddress import ip_address
from pathlib import Path
from urllib.parse import urlencode, urlparse, parse_qs, unquote, urljoin

from sqlalchemy import update

from ... import models
from ...config import settings
from ...database import get_db_context
from ...logger import log_error
from . import service
from .provider import BoundedAPI, PixivError, encrypt, decrypt, throttle, proxy_url

LOGIN_URL = "https://app-api.pixiv.net/web/v1/login"
REDIRECT_URI = "https://app-api.pixiv.net/web/v1/users/auth/pixiv/callback"


def browser_executable():
    if settings.PIXIV_OL_BROWSER_EXECUTABLE:
        path = Path(settings.PIXIV_OL_BROWSER_EXECUTABLE)
        return str(path) if path.is_file() else None
    if sys.platform == "win32":
        for path in (
            Path("C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe"),
            Path("C:/Program Files/Microsoft/Edge/Application/msedge.exe"),
        ):
            if path.is_file():
                return str(path)
    return None


def local_request(request):
    if not request.client or request.url.hostname not in {"localhost", "127.0.0.1", "::1"}:
        return False
    if any(name in request.headers for name in ("forwarded", "x-forwarded-for", "x-forwarded-host")):
        return False
    try:
        return ip_address(request.client.host).is_loopback
    except ValueError:
        return False


def require_root(db, actor_id):
    user = service.require_actor(db, actor_id)
    if user.role != "root" or user.qq_number != settings.ROOT_QQ:
        raise PixivError("permission_revoked")


def callback_code(url):
    try:
        parsed = urlparse(url)
        if parsed.username or parsed.password or parsed.fragment or parsed.port not in (None, 443):
            return None
    except ValueError:
        return None
    if (
        parsed.scheme == "https"
        and parsed.hostname == "app-api.pixiv.net"
        and parsed.path == "/web/v1/users/auth/pixiv/callback"
    ) or (parsed.scheme == "pixiv" and parsed.netloc == "account" and parsed.path == "/login"):
        values = parse_qs(parsed.query, keep_blank_values=True).get("code", [])
        if len(values) == 1 and 1 <= len(values[0]) <= 2048:
            return values[0]
    return None


def authorization_input(value):
    """Accept a pasted callback, including Firefox's colonless HTTPS navigation."""
    value = value.strip()
    if len(value) > 8192:
        return None
    if len(value) >= 2 and (value[0], value[-1]) in (("\"", "\""), ("'", "'"), ("“", "”"), ("‘", "’")):
        value = value[1:-1].strip()
    if not value or any(char.isspace() or ord(char) <= 32 or ord(char) == 127 for char in value):
        return None
    value = re.sub(r"^https//(?=app-api\.pixiv\.net(?:[/?]|$))", "https://", value, flags=re.I)
    if value.lower().startswith("app-api.pixiv.net/"):
        value = "https://" + value
    code = value if re.fullmatch(r"[a-zA-Z0-9._-]{1,2048}", value) else callback_code(value)
    return code if code and re.fullmatch(r"[a-zA-Z0-9._-]{1,2048}", code) else None


def login_url(verifier):
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    return (
        LOGIN_URL
        + "?"
        + urlencode({"code_challenge": challenge, "code_challenge_method": "S256", "client": "pixiv-android"})
    )


def open_default_browser(url):
    """Open only our generated Pixiv login page using the OS URL association."""
    parsed = urlparse(url)
    if parsed.scheme != "https" or parsed.netloc != "app-api.pixiv.net" or parsed.path != "/web/v1/login":
        return False
    try:
        if sys.platform == "win32":
            os.startfile(url)
            return True
        import webbrowser

        return bool(webbrowser.open_new_tab(url))
    except Exception:
        return False


def manual_session(row):
    return {
        "id": row.id,
        "url": login_url(decrypt(row.verifier)),
        "automatic": False,
        "expires_in": max(0, int((row.expires_at - datetime.utcnow()).total_seconds())),
    }


def start(actor_id, automatic=False):
    verifier = secrets.token_urlsafe(48)
    session_id = secrets.token_hex(16)
    url = login_url(verifier)
    with get_db_context() as db:
        require_root(db, actor_id)
        db.query(models.PixivLoginSession).filter(
            models.PixivLoginSession.expires_at < datetime.utcnow() - timedelta(days=1)
        ).delete()
        db.query(models.PixivLoginSession).filter(
            models.PixivLoginSession.actor_id == actor_id,
            models.PixivLoginSession.status.in_(("waiting", "browser", "cli", "exchanging")),
        ).update({"status": "cancelled", "verifier": ""})
        db.add(
            models.PixivLoginSession(
                id=session_id,
                actor_id=actor_id,
                verifier=encrypt(verifier),
                status="browser" if automatic else "waiting",
                expires_at=datetime.utcnow() + timedelta(minutes=10),
            )
        )
    if automatic:
        threading.Thread(
            target=browser_login, args=(session_id, actor_id, url), daemon=True, name="pixiv_login"
        ).start()
    return {"id": session_id, "url": url, "automatic": automatic, "expires_in": 600}


def exchange(code, verifier):
    options = {"timeout": max(5, settings.PIXIV_REQUEST_TIMEOUT_SECONDS), "allow_redirects": False}
    proxy = proxy_url()
    if proxy:
        options["proxies"] = {"https": proxy, "http": proxy}
    api = BoundedAPI(**options)
    try:
        throttle()
        stamp = datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%S+00:00")
        response = api.requests_call(
            "POST",
            "https://oauth.secure.pixiv.net/auth/token",
            headers={
                "User-Agent": "PixivAndroidApp/5.0.234 (Android 11; Pixel 5)",
                "X-Client-Time": stamp,
                "X-Client-Hash": hashlib.md5((stamp + api.hash_secret).encode()).hexdigest(),
            },
            data={
                "client_id": api.client_id,
                "client_secret": api.client_secret,
                "grant_type": "authorization_code",
                "code": code,
                "code_verifier": verifier,
                "include_policy": "true",
                "redirect_uri": REDIRECT_URI,
            },
        )
        try:
            data = response.json()
        except ValueError:
            raise PixivError("login_response_invalid") from None
        payload = data.get("response", data) if isinstance(data, dict) else None
        token = payload.get("refresh_token") if isinstance(payload, dict) else None
        if not isinstance(token, str) or not 20 <= len(token) <= 4096:
            raise PixivError("login_response_invalid")
        return token
    except PixivError:
        raise
    except Exception:
        raise PixivError("login_exchange_failed") from None
    finally:
        api.requests.close()


def complete(session_id, actor_id, code):
    with get_db_context() as db:
        require_root(db, actor_id)
        row = db.get(models.PixivLoginSession, session_id)
        if not row or row.actor_id != actor_id or row.expires_at <= datetime.utcnow():
            raise PixivError("login_expired")
        if row.status not in ("waiting", "browser"):
            raise PixivError("login_used")
        verifier = decrypt(row.verifier)
        claimed = db.execute(
            update(models.PixivLoginSession)
            .where(
                models.PixivLoginSession.id == session_id, models.PixivLoginSession.status.in_(("waiting", "browser"))
            )
            .values(status="exchanging", verifier="")
        ).rowcount
        if not claimed:
            raise PixivError("login_used")
    stage = "exchange"
    try:
        token = exchange(code, verifier)
        from .jobs import ACCOUNT_LOCK

        with ACCOUNT_LOCK:
            with get_db_context() as db:
                require_root(db, actor_id)
                if db.get(models.PixivLoginSession, session_id).status != "exchanging":
                    raise PixivError("login_cancelled")
            stage = "connect"
            result = service.connect(token, actor_id)
        with get_db_context() as db:
            db.get(models.PixivLoginSession, session_id).status = "completed"
        return result
    except Exception as exc:
        error = exc.code if isinstance(exc, PixivError) else "login_exchange_failed"
        log_error(f"Pixiv login failed: stage={stage}, error={error}, type={type(exc).__name__}")
        fail(session_id, error)
        raise PixivError(error) from None


def fail(session_id, code):
    with get_db_context() as db:
        row = db.get(models.PixivLoginSession, session_id)
        if row and row.status not in ("completed", "cancelled"):
            row.status, row.error, row.verifier = "failed", code, ""


def capture_browser_code(context, session_id, actor_id, url):
    from playwright.sync_api import Error as BrowserError

    code = None
    rejected = False

    def capture(candidate):
        nonlocal code
        code = code or callback_code(candidate)

    def response_received(response):
        nonlocal rejected
        # HTTP redirects can carry the code before a page navigation event.
        location = response.headers.get("location")
        if location:
            capture(urljoin(response.url, location))
        parsed = urlparse(response.url)
        if (
            parsed.hostname == "app-api.pixiv.net"
            and parsed.path == "/web/v1/users/auth/pixiv/start"
            and response.status >= 400
        ):
            rejected = True

    def callback_request(route):
        capture(route.request.url)
        if callback_code(route.request.url):
            # We redeem the code ourselves; the callback page is not a success UI.
            route.abort()
        else:
            route.continue_()

    def prepare(page):
        devtools = context.new_cdp_session(page)
        devtools.send("Page.enable")
        devtools.send("Network.enable")
        devtools.on("Page.frameRequestedNavigation", lambda event: capture(event.get("url", "")))
        devtools.on("Network.requestWillBeSent", lambda event: capture(event.get("request", {}).get("url", "")))
        page.on("request", lambda request: capture(request.url))

    context.route("https://app-api.pixiv.net/web/v1/users/auth/pixiv/callback**", callback_request)
    context.on("response", response_received)
    context.on("page", prepare)
    page = context.new_page()
    try:
        page.goto(url, wait_until="domcontentloaded", timeout=60000)
    except BrowserError:
        if not code:
            raise PixivError("login_browser_navigation_failed") from None
    deadline = datetime.utcnow() + timedelta(minutes=10)
    while not code and datetime.utcnow() < deadline:
        with get_db_context() as db:
            require_root(db, actor_id)
            row = db.get(models.PixivLoginSession, session_id)
            if not row or row.status != "browser":
                return None
        if rejected:
            raise PixivError("login_request_rejected")
        if not context.pages:
            raise PixivError("login_closed")
        try:
            context.pages[0].wait_for_timeout(500)
        except BrowserError:
            if not code:
                raise PixivError("login_closed") from None
    if not code:
        raise PixivError("login_expired")
    return code


def browser_login(session_id, actor_id, url):
    stage = "open"
    try:
        try:
            from playwright.sync_api import sync_playwright, Error as BrowserError
        except ModuleNotFoundError:
            raise PixivError("login_browser_dependency_missing") from None

        with sync_playwright() as playwright:
            options = {"headless": False, "executable_path": browser_executable()}
            proxy_value = proxy_url()
            if proxy_value:
                proxy = urlparse(proxy_value)
                if proxy.scheme not in ("http", "https", "socks5") or not proxy.hostname:
                    raise PixivError("login_browser_failed")
                host = f"[{proxy.hostname}]" if ":" in proxy.hostname else proxy.hostname
                options["proxy"] = {"server": f"{proxy.scheme}://{host}" + (f":{proxy.port}" if proxy.port else "")}
                if proxy.username:
                    options["proxy"].update(username=unquote(proxy.username), password=unquote(proxy.password or ""))
            browser = playwright.chromium.launch(**options)
            try:
                context = browser.new_context()
                stage = "navigation"
                code = capture_browser_code(context, session_id, actor_id, url)
            finally:
                try:
                    browser.close()
                except BrowserError:
                    pass
        if code is None:
            return
        stage = "exchange"
        complete(session_id, actor_id, code)
    except Exception as exc:
        error = exc.code if isinstance(exc, PixivError) else "login_browser_failed"
        # Never include exception messages, URLs, codes, or token response bodies.
        log_error(f"Pixiv login failed: stage={stage}, error={error}, type={type(exc).__name__}")
        fail(session_id, error)
