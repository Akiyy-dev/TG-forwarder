"""Safe file path helpers and temporary file cleanup."""

from __future__ import annotations

import contextlib
import re
import time
from pathlib import Path

_UNSAFE_RE = re.compile(r"[^\w.\-]+", re.UNICODE)


def sanitize_filename(name: str, *, default: str = "file.bin") -> str:
    """Return a basename-safe filename without path separators."""
    base = Path(name).name if name else default
    base = base.replace("..", ".")
    cleaned = _UNSAFE_RE.sub("_", base).strip("._")
    if not cleaned or cleaned in {".", ".."}:
        return default
    # Prevent absurdly long names
    return cleaned[:180]


def safe_join(directory: Path | str, filename: str) -> Path:
    """Join directory with sanitized filename and reject path traversal."""
    root = Path(directory).resolve()
    safe_name = sanitize_filename(filename)
    candidate = (root / safe_name).resolve()
    if not str(candidate).startswith(str(root)):
        msg = "Path traversal detected"
        raise ValueError(msg)
    return candidate


def ensure_dir(path: Path | str) -> Path:
    directory = Path(path)
    directory.mkdir(parents=True, exist_ok=True)
    return directory


def cleanup_expired_files(directory: Path | str, ttl_minutes: int) -> int:
    """Delete files older than ttl_minutes. Returns number of deleted files."""
    root = Path(directory)
    if not root.exists():
        return 0
    cutoff = time.time() - (ttl_minutes * 60)
    deleted = 0
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        try:
            if path.stat().st_mtime < cutoff:
                path.unlink(missing_ok=True)
                deleted += 1
        except OSError:
            continue
    return deleted


def remove_file(path: str | Path | None) -> None:
    if not path:
        return
    with contextlib.suppress(OSError):
        Path(path).unlink(missing_ok=True)
