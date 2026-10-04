"""Pinned pixiv-cli adapter. Child output and credentials never reach application logs."""

import json
import ntpath
import os
from pathlib import Path
import re
import socket
import subprocess
import sys
import threading
from datetime import datetime, timedelta
from urllib.parse import parse_qs, urlparse

from sqlalchemy import update

from ... import models
from ...config import settings
from ...database import get_db_context
from ...logger import log_error
from . import login, service
from .jobs import ACCOUNT_LOCK
from .provider import PixivError, proxy_url
from .windows_process import ChildJob

_RUN_LOCK = threading.Lock()  # pixiv-cli shares one protocol endpoint per OS user.
_STATE_LOCK = threading.Lock()
_STATES = {}
OUTPUT_LIMIT = 128 * 1024


def executable():
    path = (
        Path(settings.PIXIV_CLI_EXECUTABLE)
        if settings.PIXIV_CLI_EXECUTABLE
        else (Path(settings.DATA_PATH) / "pixiv-cli" / ("pixiv.exe" if sys.platform == "win32" else "pixiv"))
    )
    return str(path.resolve()) if path.is_file() else None


def process_options():
    env = dict(os.environ, PIXIV_LOG_LEVEL="info")  # v1.1.1 accepts only info/debug.
    # USERPROFILE/HOME must stay unchanged: the OS-launched protocol handler uses the same store.
    options = {"env": env, "stdin": subprocess.DEVNULL, "stdout": subprocess.PIPE, "stderr": subprocess.PIPE}
    if sys.platform == "win32":
        options["creationflags"] = subprocess.CREATE_NO_WINDOW
    return options


def run_command(path, args, timeout=20):
    try:
        result = subprocess.run([path, *args], timeout=timeout, **process_options())
    except (OSError, subprocess.TimeoutExpired):
        raise PixivError("login_cli_failed") from None
    if result.returncode != 0 or len(result.stdout) > OUTPUT_LIMIT:
        raise PixivError("login_cli_failed")
    return result.stdout


def ensure_handler(path):
    if run_command(path, ["--version"]).decode("utf-8", "replace").strip() != "pixiv v1.1.1":
        raise PixivError("login_cli_version")
    # This version's official installer uses the same hidden handler command.
    run_command(path, ["auth", "_install-handler"])
    if sys.platform == "win32":
        import winreg

        try:
            if not all(Path(value).is_file() for value in handler_paths()):
                raise PixivError("login_cli_handler_failed")
            if not windows_handler_registered(path, winreg):
                repair_windows_handler(path, winreg)
            if not windows_handler_registered(path, winreg):
                raise PixivError("login_cli_handler_failed")
        except OSError:
            raise PixivError("login_cli_handler_failed") from None


def handler_paths():
    return str(Path(sys.executable).with_name("pythonw.exe")), str(Path(__file__).with_name("protocol_handler.py"))


def handler_command(path):
    interpreter, script = handler_paths()
    # A shell would interpret callback parameters. Keep all paths and the URI as separate argv values.
    return f'"{interpreter}" "{script}" --executable "{path}" "%1"'


def same_path(first, second):
    if ntpath.normcase(ntpath.normpath(first)) == ntpath.normcase(ntpath.normpath(second)):
        return True
    try:
        return os.path.samefile(first, second)
    except OSError:
        return False


def handler_command_matches(command, path):
    if not isinstance(command, str):
        return False
    match = re.fullmatch(r'\s*"([^"\r\n]+)"\s+"([^"\r\n]+)"\s+--executable\s+"([^"\r\n]+)"\s+"%1"\s*', command)
    if not match:
        return False
    return all(
        same_path(registered, expected) for registered, expected in zip(match.groups(), (*handler_paths(), path))
    )


def windows_handler_registered(path, registry):
    try:
        with registry.OpenKey(registry.HKEY_CURRENT_USER, r"Software\Classes\pixiv") as key:
            protocol, kind = registry.QueryValueEx(key, "URL Protocol")
        with registry.OpenKey(registry.HKEY_CURRENT_USER, r"Software\Classes\pixiv\shell\open\command") as key:
            command, command_kind = registry.QueryValueEx(key, "")
        return (
            protocol == ""
            and kind == registry.REG_SZ
            and command_kind == registry.REG_SZ
            and handler_command_matches(command, path)
        )
    except FileNotFoundError:
        return False


def repair_windows_handler(path, registry):
    """Repair only our three HKCU values; retain originals and unrelated registry entries.

    v1.1.1's _install-handler trusts its manifest and can return success while the
    actual association is absent or points at an older checkout.
    """
    root = r"Software\Classes\pixiv"
    values = [
        (root, "", "URL:Pixiv Protocol"),
        (root, "URL Protocol", ""),
        (root + r"\shell\open\command", "", handler_command(path)),
    ]
    originals = []
    for subkey, name, _ in values:
        try:
            with registry.OpenKey(registry.HKEY_CURRENT_USER, subkey) as key:
                value, kind = registry.QueryValueEx(key, name)
            originals.append(
                {
                    "key": subkey,
                    "name": name,
                    "kind": kind,
                    "value": value.hex() if isinstance(value, bytes) else value,
                    "binary": isinstance(value, bytes),
                }
            )
        except FileNotFoundError:
            originals.append({"key": subkey, "name": name, "missing": True})
    backup = Path(settings.DATA_PATH) / "pixiv-cli" / "handler-backup.json"
    backup.parent.mkdir(parents=True, exist_ok=True)
    if not backup.exists():
        with backup.open("x", encoding="utf-8") as file:
            json.dump({"version": 1, "values": originals}, file)
    for subkey, name, value in values:
        with registry.CreateKeyEx(registry.HKEY_CURRENT_USER, subkey, 0, registry.KEY_SET_VALUE) as key:
            registry.SetValueEx(key, name, 0, registry.REG_SZ, value)
    # Make the updated per-user URL association visible to already-running applications.
    notify_windows_associations()


def notify_windows_associations():
    import ctypes

    ctypes.windll.shell32.SHChangeNotify(0x08000000, 0, None, None)


def endpoint_path():
    return Path.home() / ".pixiv-cli" / "url-handler-endpoint"


def cleanup_endpoint(expected):
    path = endpoint_path()
    try:
        if path.read_text(encoding="utf-8").strip() == expected:
            path.unlink()
    except OSError:
        pass


def prepare_endpoint(expected):
    """Avoid replacing another CLI session, and recover only our own stale endpoint."""
    path = endpoint_path()
    marker = Path(settings.DATA_PATH) / "pixiv-cli" / "bridge.json"
    if path.exists():
        existing = path.read_text(encoding="utf-8").strip()
        owned = marker.exists() and json.loads(marker.read_text(encoding="utf-8")).get("endpoint") == existing
        parsed = urlparse(existing)
        if not owned or parsed.hostname != "127.0.0.1" or not parsed.port:
            raise PixivError("login_cli_busy")
        try:
            with socket.create_connection(("127.0.0.1", parsed.port), timeout=0.2):
                raise PixivError("login_cli_busy")
        except OSError:
            cleanup_endpoint(existing)
    marker.parent.mkdir(parents=True, exist_ok=True)
    marker.write_text(json.dumps({"endpoint": expected}), encoding="utf-8")


def install_endpoint(expected):
    path = endpoint_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".picmanager.tmp")
    temporary.write_text(expected + "\n", encoding="utf-8")
    os.replace(temporary, path)


def phase(session_id):
    with _STATE_LOCK:
        state = _STATES.get(session_id)
        return state["phase"] if state else None


def session_json(row):
    return {
        "id": row.id,
        "automatic": True,
        "engine": "pixiv-cli",
        "expires_in": max(0, int((row.expires_at - datetime.utcnow()).total_seconds())),
    }


def require_active(session_id, actor_id, status="cli"):
    with get_db_context() as db:
        login.require_root(db, actor_id)
        row = db.get(models.PixivLoginSession, session_id)
        if not row or row.actor_id != actor_id or row.status != status:
            raise PixivError("login_cancelled")
        if row.expires_at <= datetime.utcnow():
            raise PixivError("login_expired")


def start(actor_id):
    import secrets

    path = executable()
    if not path:
        raise PixivError("login_cli_not_installed")
    session_id = secrets.token_hex(16)
    with ACCOUNT_LOCK, get_db_context() as db:
        login.require_root(db, actor_id)
        db.query(models.PixivLoginSession).filter(
            models.PixivLoginSession.actor_id == actor_id,
            models.PixivLoginSession.status.in_(("waiting", "browser", "cli", "exchanging")),
        ).update({"status": "cancelled", "verifier": ""})
        db.add(
            models.PixivLoginSession(
                id=session_id,
                actor_id=actor_id,
                verifier="",
                status="cli",
                expires_at=datetime.utcnow() + timedelta(minutes=10),
            )
        )
    state = {"stop": threading.Event(), "phase": "starting"}
    thread = threading.Thread(
        target=run_login, args=(session_id, actor_id, path, state), daemon=True, name="pixiv_cli_login"
    )
    state["thread"] = thread
    with _STATE_LOCK:
        _STATES[session_id] = state
    thread.start()
    return {"id": session_id, "automatic": True, "engine": "pixiv-cli", "expires_in": 600}


def validated_login_url(value):
    parsed = urlparse(value)
    query = parse_qs(parsed.query)
    return (
        parsed.scheme == "https"
        and parsed.netloc == "app-api.pixiv.net"
        and parsed.path == "/web/v1/login"
        and not parsed.fragment
        and query.get("code_challenge_method") == ["S256"]
        and query.get("client") == ["pixiv-android"]
        and len(query.get("code_challenge", [])) == 1
        and bool(re.fullmatch(r"[a-zA-Z0-9_-]{43}", query["code_challenge"][0]))
    )


def cli_error(stderr):
    # Match categories in memory; never return third-party error text.
    text = stderr.lower()
    # v1.1.1's SDK removes HTTP status/URLs and prints `pixiv:Complete: <reason>`.
    sdk_error = re.search(r"(?:^|\n)error:\s*pixiv:([a-z][a-z0-9_]*):\s*([a-z_]+)\b", text)
    if sdk_error:
        operation, reason = sdk_error.groups()
        categories = {
            "credentials_expired": "login_exchange_failed",
            "rate_limited": "rate_limited",
            "forbidden": "access_denied",
            "malformed_upstream_response": "login_response_invalid",
            "local_state_error": "login_cli_storage_failed",
            "upstream_error": "login_service_unavailable",
        }
        if reason in categories:
            return categories[reason]
        if reason == "upstream_unavailable" and operation == "complete":
            return "login_network_error"
        if reason == "invalid_argument" and operation == "complete":
            return "login_callback_invalid"
    if "deadline exceeded" in text:
        return "login_expired"
    if "status 429" in text:
        return "rate_limited"
    if any(
        word in text
        for word in (
            "dial tcp",
            "tls handshake",
            "connection refused",
            "network is unreachable",
            "upstream transport failed",
        )
    ):
        return "login_network_error"
    if re.search(r"status[ :]+5\d\d", text):
        return "login_service_unavailable"
    if "oauth" in text or "exchange" in text:
        return "login_authorization_rejected"
    return "login_cli_failed"


def run_login(session_id, actor_id, path, state):
    process = None
    child_job = None
    endpoint = None
    readers = []
    acquired = False
    try:
        acquired = _RUN_LOCK.acquire(timeout=5)
        if not acquired:
            raise PixivError("login_cli_busy")
        require_active(session_id, actor_id)
        ensure_handler(path)
        with socket.socket() as reservation:
            reservation.bind(("127.0.0.1", 0))
            port = reservation.getsockname()[1]
        address = f"127.0.0.1:{port}"
        endpoint = f"http://{address}/callback"
        prepare_endpoint(endpoint)
        args = [
            path,
            "auth",
            "login",
            "--json",
            "--no-open",
            "--use=false",
            "--timeout",
            "10m",
            "--addr",
            address,
            "--relay-public-url=",
            "--relay-listen-addr=",
        ]
        proxy = proxy_url()
        args += ["--proxy", proxy] if proxy else ["--no-proxy"]
        require_active(session_id, actor_id)
        process = subprocess.Popen(args, **process_options())
        # Closing the server also closes this non-inherited job handle and kills its CLI child.
        if sys.platform == "win32":
            child_job = ChildJob(process)
        output = {"stdout": bytearray(), "stderr": bytearray(), "url": None, "ready": False, "overflow": False}

        def collect(stream, name):
            for line in iter(lambda: stream.readline(8192), b""):
                if len(output[name]) + len(line) > OUTPUT_LIMIT:
                    output["overflow"] = True
                    continue
                output[name].extend(line)
                if name == "stderr":
                    value = line.decode("utf-8", "replace").strip()
                    if value.startswith("https://") and validated_login_url(value):
                        output["url"] = value
                    if value == f"Manual fallback page: http://{address}/":
                        output["ready"] = True

        for name, stream in (("stdout", process.stdout), ("stderr", process.stderr)):
            thread = threading.Thread(target=collect, args=(stream, name), daemon=True)
            thread.start()
            readers.append(thread)
        opened = False
        while process.poll() is None:
            if state["stop"].wait(0.2):
                raise PixivError("login_interrupted")
            require_active(session_id, actor_id)
            if output["overflow"]:
                raise PixivError("login_cli_failed")
            if not opened and output["ready"] and output["url"]:
                # --no-open avoids the CLI's temporary registry override. We own this endpoint only.
                with ACCOUNT_LOCK:
                    require_active(session_id, actor_id)
                    install_endpoint(endpoint)
                    if not login.open_default_browser(output["url"]):
                        raise PixivError("login_cli_browser_failed")
                output["url"] = None
                opened, state["phase"] = True, "browser"
        for thread in readers:
            thread.join(timeout=2)
        require_active(session_id, actor_id)
        if process.returncode != 0:
            raise PixivError(cli_error(output["stderr"].decode("utf-8", "replace")))
        if output["overflow"] or not opened:
            raise PixivError("login_cli_failed")
        account = json.loads(output["stdout"])
        uid = account.get("user_id")
        if type(uid) is not int or uid <= 0 or account.get("has_token") is not True:
            raise PixivError("login_response_invalid")
        # Export only the account returned by this login; stdout remains in memory.
        token = run_command(path, ["auth", "export", str(uid)]).decode("utf-8").strip()
        if not re.fullmatch(r"[a-zA-Z0-9._-]{20,4096}", token):
            raise PixivError("login_response_invalid")
        with ACCOUNT_LOCK:
            require_active(session_id, actor_id)
            with get_db_context() as db:
                claimed = db.execute(
                    update(models.PixivLoginSession)
                    .where(models.PixivLoginSession.id == session_id, models.PixivLoginSession.status == "cli")
                    .values(status="exchanging")
                ).rowcount
                if not claimed:
                    raise PixivError("login_cancelled")
            state["phase"] = "connecting"
            user = {"id": str(uid), "name": str(account.get("username") or uid)}
            service.connect_cli(token, user, actor_id, session_id)
    except Exception as exc:
        code = exc.code if isinstance(exc, PixivError) else "login_cli_failed"
        log_error(f"Pixiv CLI login failed: error={code}, type={type(exc).__name__}")
        login.fail(session_id, code)
    finally:
        try:
            if process is not None:
                if process.poll() is None:
                    process.kill()
                process.wait(timeout=5)
                for thread in readers:
                    thread.join(timeout=2)
                for stream in (process.stdout, process.stderr):
                    stream.close()
        finally:
            if child_job is not None:
                child_job.close()
            if endpoint:
                cleanup_endpoint(endpoint)
            with _STATE_LOCK:
                _STATES.pop(session_id, None)
            if acquired:
                _RUN_LOCK.release()


def shutdown():
    with _STATE_LOCK:
        states = list(_STATES.values())
    for state in states:
        state["stop"].set()
    for state in states:
        state["thread"].join(timeout=5)
