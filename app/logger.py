from __future__ import annotations

from typing import Callable
import sys

LogHook = Callable[[str, str], None]

_COLOR_RESET = "\033[0m"
_COLOR_INFO = "\033[94m"
_COLOR_SUCCESS = "\033[92m"
_COLOR_ERROR = "\033[91m"


def _default_log_hook(level: str, message: str) -> None:
    color = _COLOR_INFO
    if level == "SUCCESS":
        color = _COLOR_SUCCESS
    elif level == "ERROR":
        color = _COLOR_ERROR

    formatted = f"[{level}] {message}"
    sys.stdout.write(f"{color}{formatted}{_COLOR_RESET}\n")


_log_hook: LogHook = _default_log_hook


def set_log_hook(hook: LogHook) -> None:
    """设置日志hook，方便外部替换输出方式。"""
    global _log_hook
    _log_hook = hook


def _log(level: str, message: str) -> None:
    _log_hook(level, message)


def log_info(message: str) -> None:
    _log("INFO", message)


def log_success(message: str) -> None:
    _log("SUCCESS", message)


def log_error(message: str) -> None:
    _log("ERROR", message)
