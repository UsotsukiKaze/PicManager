from types import SimpleNamespace

import pytest

from app.config import _resolve_secret_key


def test_configured_secret_key_is_preserved(tmp_path):
    configured = "a" * 48
    settings = SimpleNamespace(SECRET_KEY=configured, DATA_PATH=str(tmp_path))

    assert _resolve_secret_key(settings) == configured
    assert not (tmp_path / ".secret_key").exists()


def test_placeholder_secret_is_generated_once_and_persisted(tmp_path):
    settings = SimpleNamespace(
        SECRET_KEY="your-secret-key-change-this-in-production-min-32-chars",
        DATA_PATH=str(tmp_path),
    )

    first = _resolve_secret_key(settings)
    second = _resolve_secret_key(settings)

    assert first == second
    assert len(first) >= 32
    assert (tmp_path / ".secret_key").read_text(encoding="utf-8") == first


def test_short_configured_secret_is_rejected(tmp_path):
    settings = SimpleNamespace(SECRET_KEY="too-short", DATA_PATH=str(tmp_path))

    with pytest.raises(RuntimeError, match="at least 32"):
        _resolve_secret_key(settings)
