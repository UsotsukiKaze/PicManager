"""Standalone, silent Windows protocol entry point; no project imports or shell.

Cobra rejects binaries started by Explorer before running their callback command.
Launching the unchanged official CLI from pythonw avoids that startup guard.
"""

import os
from pathlib import Path
import re
import subprocess
import sys
from urllib.parse import parse_qs, urlsplit


def allowed_callback(value):
    if not isinstance(value, str) or len(value) > 8192 or any(ord(char) <= 32 for char in value):
        return False
    try:
        parsed = urlsplit(value)
        query = parse_qs(parsed.query, max_num_fields=8)
        codes = query.get("code", [])
        return (
            parsed.scheme.lower() == "pixiv"
            and parsed.netloc.lower() == "account"
            and parsed.path == "/login"
            and not parsed.fragment
            and len(codes) == 1
            and bool(re.fullmatch(r"[a-zA-Z0-9._-]{1,4096}", codes[0]))
        )
    except ValueError:
        return False


def main(args=None):
    args = sys.argv[1:] if args is None else args
    if len(args) != 3 or args[0] != "--executable" or not allowed_callback(args[2]):
        return 2
    binary = Path(args[1])
    if not binary.is_absolute() or not binary.is_file():
        return 2
    options = {
        "stdin": subprocess.DEVNULL,
        "stdout": subprocess.DEVNULL,
        "stderr": subprocess.DEVNULL,
        "env": dict(os.environ, PIXIV_LOG_LEVEL="info"),
        "timeout": 20,
    }
    if sys.platform == "win32":
        options["creationflags"] = subprocess.CREATE_NO_WINDOW
    try:
        return subprocess.run([str(binary), "auth", "_callback", args[2]], **options).returncode
    except (OSError, subprocess.TimeoutExpired):
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
