"""Exercise the adapter with a real child process, isolated DB and synthetic OAuth output."""

import subprocess
import sys
import time
import json
from contextlib import contextmanager
from datetime import datetime, timedelta

import pytest

from app import models
from app.config import settings
from app.integrations.pixiv_ol import cli_login, login, provider, service
from app.integrations.pixiv_ol import protocol_handler
import test_pixiv_ol

environment = test_pixiv_ol.environment


@pytest.fixture
def cli_child(environment, monkeypatch):
    context, client, tmp = environment
    binary = tmp / "pixiv.exe"
    binary.touch()
    monkeypatch.setattr(settings, "PIXIV_CLI_EXECUTABLE", str(binary))
    endpoint = tmp / "cli-home/url-handler-endpoint"
    monkeypatch.setattr(cli_login, "endpoint_path", lambda: endpoint)
    monkeypatch.setattr(cli_login, "ensure_handler", lambda path: None)
    monkeypatch.setattr(login, "local_request", lambda _: True)
    gate = tmp / "finish"
    child = tmp / "child.py"
    child.write_text(
        """
import sys, time, json
from pathlib import Path
gate = Path(sys.argv[1])
address = sys.argv[sys.argv.index('--addr') + 1]
print('Open this Pixiv login URL:', file=sys.stderr, flush=True)
print('https://app-api.pixiv.net/web/v1/login?code_challenge=' + 'a'*43 + '&code_challenge_method=S256&client=pixiv-android', file=sys.stderr, flush=True)
print('Manual fallback page: http://' + address + '/', file=sys.stderr, flush=True)
while not gate.exists(): time.sleep(0.01)
if gate.read_text() == 'fail':
 print('OAuth exchange status 503; synthetic-private-value', file=sys.stderr, flush=True)
 sys.exit(1)
print(json.dumps({'user_id':7,'username':'CLI account','has_token':True}), flush=True)
""",
        encoding="utf-8",
    )
    real_popen = subprocess.Popen
    children = []

    def popen(args, **kwargs):
        process = real_popen([sys.executable, str(child), str(gate), *args[1:]], **kwargs)
        process._pixiv_test_args = args
        children.append(process)
        return process

    monkeypatch.setattr(cli_login.subprocess, "Popen", popen)
    exports, opened = [], []

    def export(path, args, timeout=20):
        exports.append(args)
        return b"synthetic-refresh-token-1234567890\n"

    monkeypatch.setattr(cli_login, "run_command", export)
    monkeypatch.setattr(login, "open_default_browser", lambda url: opened.append(url) or True)
    return context, client, tmp, gate, endpoint, exports, opened, children


def wait_until(check, timeout=6):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if check():
            return
        time.sleep(0.02)
    pytest.fail("CLI adapter did not reach expected state")


def begin(cli_child):
    _, client, _, _, _, _, opened, _ = cli_child
    result = client.post("/api/pixiv-ol/account/login", json={"mode": "default_browser"})
    assert result.status_code == 200
    session = result.json()
    assert session["automatic"] and session["engine"] == "pixiv-cli"
    assert "url" not in session
    wait_until(lambda: bool(opened))
    return session["id"]


def test_cli_automatically_imports_only_the_new_login_preserving_preferences(cli_child, monkeypatch):
    context, client, _, gate, endpoint, exports, opened, _ = cli_child
    monkeypatch.setattr(service, "Provider", lambda _: pytest.fail("CLI login redundantly refreshed its token"))
    sid = begin(cli_child)
    assert endpoint.exists()
    pending = client.get("/api/pixiv-ol/account/login/pending").json()["session"]
    assert pending["id"] == sid and pending["automatic"]
    assert "url" not in pending and "verifier" not in pending
    gate.write_text("ok")
    wait_until(lambda: client.get(f"/api/pixiv-ol/account/login/{sid}").json()["status"] == "completed")
    wait_until(lambda: not endpoint.exists())
    assert exports == [["auth", "export", "7"]]
    assert len(opened) == 1
    with context() as db:
        account = db.get(models.PixivAccount, 1)
        assert account.name == "CLI account" and account.revision == "rev"
        assert account.preferences == {"groups": {"1": {"enabled": True}}}
        assert provider.decrypt(account.credential) == "synthetic-refresh-token-1234567890"
        assert db.get(models.PixivLoginSession, sid).verifier == ""
    assert client.get("/api/pixiv-ol/account/login/pending").json()["session"] is None


def test_cancel_cli_terminates_child_and_cleans_only_its_endpoint(cli_child):
    _, client, _, _, endpoint, exports, _, children = cli_child
    sid = begin(cli_child)
    assert client.delete(f"/api/pixiv-ol/account/login/{sid}").status_code == 200
    wait_until(lambda: children[0].poll() is not None and not endpoint.exists())
    assert client.get(f"/api/pixiv-ol/account/login/{sid}").json()["status"] == "cancelled"
    assert not exports


def test_cli_expiry_terminates_child_without_connecting(cli_child):
    context, client, _, _, endpoint, exports, _, children = cli_child
    sid = begin(cli_child)
    with context() as db:
        db.get(models.PixivLoginSession, sid).expires_at = datetime.utcnow() - timedelta(seconds=1)
    wait_until(lambda: children[0].poll() is not None and not endpoint.exists())
    status = client.get(f"/api/pixiv-ol/account/login/{sid}").json()
    assert status["error"] == "login_expired" and not exports


def test_cli_failure_returns_category_without_raw_output(cli_child, monkeypatch):
    _, client, _, gate, endpoint, exports, _, _ = cli_child
    logs = []
    monkeypatch.setattr(cli_login, "log_error", logs.append)
    sid = begin(cli_child)
    gate.write_text("fail")
    wait_until(lambda: client.get(f"/api/pixiv-ol/account/login/{sid}").json()["status"] == "failed")
    result = client.get(f"/api/pixiv-ol/account/login/{sid}")
    assert result.json()["error"] == "login_service_unavailable" and not exports
    assert "synthetic-private-value" not in result.text + "".join(logs)
    assert "code_challenge" not in "".join(logs)
    wait_until(lambda: not endpoint.exists())


def test_cli_login_requires_local_root_and_configured_executable(environment, monkeypatch):
    _, client, _ = environment
    monkeypatch.setattr(login, "local_request", lambda _: True)
    assert (
        client.post("/api/pixiv-ol/account/login", json={"mode": "cli"}).json()["detail"] == "login_cli_not_installed"
    )
    monkeypatch.setattr(login, "local_request", lambda _: False)
    assert client.post("/api/pixiv-ol/account/login", json={"mode": "cli"}).json()["detail"] == "login_cli_local_only"
    client.cookies.set("session_id", "session-2")
    assert client.post("/api/pixiv-ol/account/login", json={"mode": "cli"}).status_code == 403


@pytest.mark.skipif(sys.platform != "win32", reason="Windows system proxy")
def test_cli_inherits_system_proxy_instead_of_forcing_direct(cli_child, monkeypatch):
    _, client, _, _, _, _, _, children = cli_child
    monkeypatch.setattr(settings, "PIXIV_PROXY", "")
    monkeypatch.setattr(settings, "PIXIV_USE_SYSTEM_PROXY", True)
    monkeypatch.setattr(
        provider, "getproxies", lambda: {"http": "http://127.0.0.1:2000", "https": "http://127.0.0.1:3000"}
    )
    sid = begin(cli_child)
    args = children[0]._pixiv_test_args
    assert args[args.index("--proxy") + 1] == "http://127.0.0.1:3000"
    assert "--no-proxy" not in args
    client.delete(f"/api/pixiv-ol/account/login/{sid}").raise_for_status()
    wait_until(lambda: children[0].poll() is not None)


@pytest.mark.parametrize(
    "configured, automatic, expected",
    [
        ("http://explicit.example:1234", True, "http://explicit.example:1234"),
        ("", False, None),
    ],
)
def test_proxy_override_and_direct_mode_do_not_consult_system(configured, automatic, expected, monkeypatch):
    monkeypatch.setattr(settings, "PIXIV_PROXY", configured)
    monkeypatch.setattr(settings, "PIXIV_USE_SYSTEM_PROXY", automatic)
    monkeypatch.setattr(provider, "getproxies", lambda: pytest.fail("system proxy unexpectedly consulted"))
    assert provider.proxy_url() == expected


@pytest.mark.parametrize(
    "proxy", ["127.0.0.1:7897", "http://localhost:bad", "http://localhost:0", "http://localhost:7897?key=secret"]
)
def test_invalid_proxy_never_exposes_its_content(proxy, monkeypatch):
    monkeypatch.setattr(settings, "PIXIV_PROXY", proxy)
    with pytest.raises(provider.PixivError, match="^pixiv_proxy_invalid$"):
        provider.proxy_url()


@pytest.mark.skipif(sys.platform != "win32", reason="Windows system proxy")
def test_api_exchange_refresh_and_download_share_cli_system_proxy(environment, monkeypatch):
    from types import SimpleNamespace

    _, _, tmp = environment
    monkeypatch.setattr(settings, "PIXIV_PROXY", "")
    monkeypatch.setattr(settings, "PIXIV_USE_SYSTEM_PROXY", True)
    monkeypatch.setattr(provider, "getproxies", lambda: {"https": "http://127.0.0.1:3000"})
    api_options, download_options = [], []

    class API:
        hash_secret = "synthetic"
        client_id = "synthetic"
        client_secret = "synthetic"
        refresh_token = "synthetic-refresh-token-1234567890"
        requests = SimpleNamespace(close=lambda: None)

        def __init__(self, **options):
            api_options.append(options)

        def auth(self, **kwargs):
            return {"user": {"id": 7, "name": "Synthetic"}}

        def requests_call(self, *args, **kwargs):
            return SimpleNamespace(json=lambda: {"refresh_token": self.refresh_token})

    class Client:
        def __init__(self, **options):
            download_options.append(options)

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        @contextmanager
        def stream(self, *args, **kwargs):
            yield SimpleNamespace(
                is_redirect=False,
                headers={"content-type": "image/png"},
                raise_for_status=lambda: None,
                iter_bytes=lambda size: iter([b"synthetic image"]),
            )

    monkeypatch.setattr(provider, "BoundedAPI", API)
    monkeypatch.setattr(login, "BoundedAPI", API)
    monkeypatch.setattr(provider.httpx, "Client", Client)
    provider.Provider(API.refresh_token).close()
    assert login.exchange("synthetic-code", "synthetic-verifier") == API.refresh_token
    provider.download("https://i.pximg.net/img-original/synthetic.png", tmp / "image.png")
    assert len(api_options) == 2
    assert all(
        options["proxies"] == {"http": "http://127.0.0.1:3000", "https": "http://127.0.0.1:3000"}
        for options in api_options
    )
    assert download_options[0]["proxy"] == "http://127.0.0.1:3000"
    assert download_options[0]["trust_env"] is False


@pytest.mark.parametrize(
    "message, expected",
    [
        ("error: pixiv:Complete: upstream_unavailable: transport: timeout", "login_network_error"),
        ("error: pixiv:Complete: upstream_unavailable: transport: tls", "login_network_error"),
        ("error: pixiv:Complete: credentials_expired", "login_exchange_failed"),
        ("error: pixiv:Complete: rate_limited", "rate_limited"),
        ("error: pixiv:Complete: forbidden", "access_denied"),
        ("error: pixiv:Complete: malformed_upstream_response", "login_response_invalid"),
        ("error: pixiv:Complete: invalid_argument: login session was already used", "login_callback_invalid"),
        ("error: pixiv:Complete: upstream_error", "login_service_unavailable"),
        ("error: pixiv:CompleteLogin: local_state_error", "login_cli_storage_failed"),
        ("error: unsupported private error", "login_cli_failed"),
    ],
)
def test_cli_error_recognizes_pinned_sdk_redacted_messages(message, expected):
    assert cli_login.cli_error(message) == expected


def test_cli_cannot_commit_after_cancel_or_root_demotion(environment):
    context, _, _ = environment
    with context() as db:
        db.add(
            models.PixivLoginSession(
                id="cli-test",
                actor_id=1,
                verifier="",
                status="cancelled",
                expires_at=datetime.utcnow() + timedelta(minutes=1),
            )
        )
    with pytest.raises(provider.PixivError, match="login_cancelled"):
        service.connect_cli("synthetic-token", {"id": "8", "name": "Other"}, 1, "cli-test")
    with context() as db:
        db.get(models.PixivLoginSession, "cli-test").status = "exchanging"
        db.get(models.User, 1).role = "admin"
    with pytest.raises(provider.PixivError, match="permission_revoked"):
        service.connect_cli("synthetic-token", {"id": "8", "name": "Other"}, 1, "cli-test")
    with context() as db:
        assert db.get(models.PixivAccount, 1).user_id == "7"
        assert db.get(models.PixivLoginSession, "cli-test").status == "exchanging"


def test_endpoint_cleanup_preserves_other_sessions(environment, monkeypatch):
    _, _, tmp = environment
    path = tmp / "endpoint"
    path.write_text("http://127.0.0.1:20000/callback\n")
    monkeypatch.setattr(cli_login, "endpoint_path", lambda: path)
    cli_login.cleanup_endpoint("http://127.0.0.1:30000/callback")
    assert path.exists()
    with pytest.raises(provider.PixivError, match="login_cli_busy"):
        cli_login.prepare_endpoint("http://127.0.0.1:30000/callback")


@pytest.mark.parametrize(
    "command, valid",
    [
        ('"D:\\Python\\pythonw.exe" "D:\\PicManager\\handler.py" --executable "D:\\PicManager\\pixiv.exe" "%1"', True),
        ('"d:/python/PYTHONW.EXE" "d:/picmanager/HANDLER.PY"  --executable "d:/picmanager/PIXIV.EXE" "%1" ', True),
        ('"D:\\PicManager\\pixiv.exe" auth _callback "%1"', False),
        ('"D:\\Python\\python.exe" "D:\\PicManager\\handler.py" --executable "D:\\PicManager\\pixiv.exe" "%1"', False),
        ('"D:\\Python\\pythonw.exe" "D:\\PicManager\\handler.py" --executable "D:\\PicManager\\pixiv.exe" "%2"', False),
        ('cmd /c "D:\\PicManager\\pixiv.exe" auth _callback "%1"', False),
    ],
)
def test_handler_command_accepts_equivalent_paths_without_accepting_other_commands(command, valid, monkeypatch):
    monkeypatch.setattr(cli_login, "handler_paths", lambda: (r"D:\Python\pythonw.exe", r"D:\PicManager\handler.py"))
    assert cli_login.handler_command_matches(command, r"D:\PicManager\pixiv.exe") is valid


class Registry:
    HKEY_CURRENT_USER, REG_SZ, KEY_SET_VALUE = 1, 1, 2

    def __init__(self, entries=None):
        self.entries = entries or {}
        self.writes = []

    @contextmanager
    def OpenKey(self, hive, path):
        if path not in self.entries:
            raise FileNotFoundError
        yield path

    def QueryValueEx(self, key, name):
        if name not in self.entries[key]:
            raise FileNotFoundError
        return self.entries[key][name]

    @contextmanager
    def CreateKeyEx(self, hive, path, reserved, access):
        self.entries.setdefault(path, {})
        yield path

    def SetValueEx(self, key, name, reserved, kind, value):
        self.entries[key][name] = value, kind
        self.writes.append((key, name))


@pytest.mark.skipif(sys.platform != "win32", reason="Windows protocol registration")
@pytest.mark.parametrize("missing", [True, False])
def test_cached_cli_install_repairs_missing_or_stale_actual_association(environment, monkeypatch, missing):
    _, _, tmp = environment
    path = str(tmp / "pixiv.exe")
    root = r"Software\Classes\pixiv"
    command_key = root + r"\shell\open\command"
    previous = '"D:\\old-checkout\\pixiv.exe" auth _callback "%1"'
    registry = Registry(
        {}
        if missing
        else {
            root: {"": ("Previous app", 1), "URL Protocol": ("", 1), "extra": ("preserved", 1)},
            command_key: {"": (previous, 1)},
        }
    )
    monkeypatch.setitem(sys.modules, "winreg", registry)
    monkeypatch.setattr(
        cli_login, "run_command", lambda path, args: b"pixiv v1.1.1\n" if args == ["--version"] else b""
    )
    monkeypatch.setattr(cli_login, "notify_windows_associations", lambda: None)
    cli_login.ensure_handler(path)
    assert cli_login.windows_handler_registered(path, registry)
    backup = tmp / "data/pixiv-cli/handler-backup.json"
    original_backup = backup.read_bytes()
    values = json.loads(original_backup)["values"]
    if missing:
        assert all(item["missing"] for item in values)
    else:
        assert values[-1]["value"] == previous
        assert registry.entries[root]["extra"] == ("preserved", 1)
    assert len(registry.writes) == 3
    cli_login.ensure_handler(path)
    assert len(registry.writes) == 3 and backup.read_bytes() == original_backup


@pytest.mark.skipif(sys.platform != "win32", reason="Windows protocol registration")
def test_equivalent_installed_handler_is_not_rewritten(environment, monkeypatch):
    _, _, tmp = environment
    root = r"Software\Classes\pixiv"
    registry = Registry(
        {
            root: {"URL Protocol": ("", 1)},
            root + r"\shell\open\command": {"": (cli_login.handler_command("d:/picmanager/PIXIV.EXE"), 1)},
        }
    )
    monkeypatch.setitem(sys.modules, "winreg", registry)
    monkeypatch.setattr(
        cli_login, "run_command", lambda path, args: b"pixiv v1.1.1\n" if args == ["--version"] else b""
    )
    cli_login.ensure_handler(r"D:\PicManager\pixiv.exe")
    assert not registry.writes and not (tmp / "data/pixiv-cli/handler-backup.json").exists()


def test_silent_protocol_entry_passes_one_opaque_argument_without_a_shell(tmp_path, monkeypatch, capsys):
    binary = tmp_path / "path with spaces" / "pixiv.exe"
    binary.parent.mkdir()
    binary.touch()
    uri = "pixiv://account/login?code=synthetic-value&state=a%26b"
    calls = []

    def run(args, **kwargs):
        calls.append((args, kwargs))
        return subprocess.CompletedProcess(args, 0)

    monkeypatch.setattr(protocol_handler.subprocess, "run", run)
    assert protocol_handler.main(["--executable", str(binary), uri]) == 0
    args, options = calls[0]
    assert args == [str(binary), "auth", "_callback", uri]
    assert not options.get("shell")
    assert options["stdin"] == options["stdout"] == options["stderr"] == subprocess.DEVNULL
    if sys.platform == "win32":
        assert options["creationflags"] == subprocess.CREATE_NO_WINDOW
    assert options["env"].get("USERPROFILE") == __import__("os").environ.get("USERPROFILE")
    assert not capsys.readouterr().out and not capsys.readouterr().err


@pytest.mark.parametrize(
    "uri",
    [
        "https://app-api.pixiv.net/web/v1/users/auth/pixiv/callback?code=synthetic",
        "pixiv://account:123/login?code=synthetic",
        "pixiv://other/login?code=synthetic",
        "pixiv://account/login?code=one&code=two",
        "pixiv://account/login?code=one#fragment",
        "pixiv://account/login?code=%22%26calc.exe",
        "pixiv://account/login?state=only",
        "pixiv://account/login?code=one\n",
    ],
)
def test_protocol_entry_rejects_malformed_or_unrelated_links_without_spawning(uri, tmp_path, monkeypatch):
    binary = tmp_path / "pixiv.exe"
    binary.touch()
    monkeypatch.setattr(
        protocol_handler.subprocess, "run", lambda *args, **kwargs: pytest.fail("invalid callback spawned")
    )
    assert protocol_handler.main(["--executable", str(binary), uri]) == 2


@pytest.mark.skipif(sys.platform != "win32", reason="Windows process lifetime")
def test_forced_server_exit_kills_its_job_child(tmp_path):
    import ctypes
    from ctypes import wintypes
    from pathlib import Path

    parent_script = tmp_path / "parent.py"
    parent_script.write_text(
        "import os, subprocess, sys, time\n"
        f"sys.path.insert(0, {str(Path(__file__).resolve().parents[1])!r})\n"
        "from app.integrations.pixiv_ol.windows_process import ChildJob\n"
        "child = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)'], creationflags=subprocess.CREATE_NO_WINDOW)\n"
        "job = ChildJob(child)\n"
        "print(child.pid, flush=True)\n"
        "time.sleep(2)\n"
        "os._exit(0)\n",
        encoding="utf-8",
    )
    parent = subprocess.Popen(
        [sys.executable, str(parent_script)],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        creationflags=subprocess.CREATE_NO_WINDOW,
    )
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel.OpenProcess.restype = wintypes.HANDLE
    kernel.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
    kernel.WaitForSingleObject.restype = wintypes.DWORD
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    child_handle = None
    try:
        child_pid = int(parent.stdout.readline())
        child_handle = kernel.OpenProcess(0x100000, False, child_pid)  # SYNCHRONIZE only.
        assert child_handle
        assert parent.wait(timeout=8) == 0
        assert kernel.WaitForSingleObject(child_handle, 5000) == 0
    finally:
        if parent.poll() is None:
            parent.kill()
        parent.wait(timeout=5)
        parent.stdout.close()
        parent.stderr.close()
        if child_handle:
            kernel.CloseHandle(child_handle)
