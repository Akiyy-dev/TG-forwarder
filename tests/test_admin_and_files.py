"""Admin auth and tempfile cleanup tests."""

from __future__ import annotations

import time
from pathlib import Path

from app.bot.middlewares import require_admin
from app.config import Settings
from app.utils.files import cleanup_expired_files, safe_join, sanitize_filename


def test_require_admin(settings_env: Settings) -> None:
    assert settings_env.is_admin(111)
    assert not settings_env.is_admin(999)
    assert require_admin(False) is not None
    assert require_admin(True) is None


def test_sanitize_and_safe_join(tmp_path: Path) -> None:
    assert sanitize_filename("../../etc/passwd") == "passwd"
    assert sanitize_filename("a/../b.txt") == "b.txt"
    path = safe_join(tmp_path, "ok.bin")
    assert path.parent == tmp_path.resolve()
    # Sanitization strips directory components before join
    nested = safe_join(tmp_path, "../outside.txt")
    assert nested.parent == tmp_path.resolve()


def test_cleanup_expired(tmp_path: Path) -> None:
    old = tmp_path / "old.bin"
    new = tmp_path / "new.bin"
    old.write_text("x", encoding="utf-8")
    new.write_text("y", encoding="utf-8")
    past = time.time() - 3600
    # set mtime old
    import os

    os.utime(old, (past, past))
    deleted = cleanup_expired_files(tmp_path, ttl_minutes=10)
    assert deleted >= 1
    assert not old.exists()
    assert new.exists()
