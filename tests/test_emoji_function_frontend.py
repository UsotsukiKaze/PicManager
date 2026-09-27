from pathlib import Path
import shutil
import subprocess

import pytest


def test_emoji_function_tag_browser_logic():
    node = shutil.which("node")
    if not node:
        pytest.skip("Node.js is required to exercise the emoji picker and form logic")
    script = Path(__file__).parent / "js" / "emoji-function-tags.test.cjs"
    result = subprocess.run([node, "--test", str(script)], capture_output=True, text=True, encoding="utf-8")
    assert result.returncode == 0, result.stdout + result.stderr
