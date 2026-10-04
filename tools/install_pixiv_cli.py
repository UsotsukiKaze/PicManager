"""Install the pinned official Windows x64 release, retaining all license files."""

import hashlib
import io
import json
import platform
from pathlib import Path, PurePosixPath
import sys
import zipfile

import httpx

VERSION = "1.1.1"
ASSET = "pixiv-cli_1.1.1_windows_amd64.zip"
SHA256 = "ec2bab3b337c40d052e5403078b0d344e9599eb7533c37661679429ca84daba9"
URL = f"https://github.com/FlanChanXwO/pixiv-cli/releases/download/v{VERSION}/{ASSET}"


def install():
    if sys.platform != "win32" or platform.machine().lower() not in ("amd64", "x86_64"):
        raise SystemExit("This installer supports Windows x64; configure PIXIV_CLI_EXECUTABLE on other platforms.")
    base = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(base))
    from app.config import settings

    target = Path(settings.DATA_PATH).resolve() / "pixiv-cli"
    response = httpx.get(URL, follow_redirects=True, timeout=60)
    response.raise_for_status()
    if hashlib.sha256(response.content).hexdigest() != SHA256:
        raise SystemExit("Release checksum mismatch; nothing installed.")
    archive = zipfile.ZipFile(io.BytesIO(response.content))
    members = archive.infolist()
    for member in members:
        relative = PurePosixPath(member.filename)
        if relative.is_absolute() or ".." in relative.parts or "\\" in member.filename or ":" in member.filename:
            raise SystemExit("Unsafe archive path; nothing installed.")
        if not (target / member.filename).resolve().is_relative_to(target):
            raise SystemExit("Unsafe archive path; nothing installed.")
    target.mkdir(parents=True, exist_ok=True)
    for member in members:
        path = target / member.filename
        if member.is_dir():
            path.mkdir(parents=True, exist_ok=True)
        else:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(archive.read(member))
    (target / "release.json").write_text(
        json.dumps({"version": VERSION, "asset": ASSET, "archive_sha256": SHA256, "source": URL}, indent=2),
        encoding="utf-8",
    )
    print(f"Installed pixiv-cli v{VERSION}; SHA-256 verified. Location: {target}")


if __name__ == "__main__":
    install()
