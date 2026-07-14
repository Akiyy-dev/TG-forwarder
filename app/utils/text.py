"""Text length and hashing helpers."""

from __future__ import annotations

import hashlib
import re

TELEGRAM_TEXT_LIMIT = 4096
TELEGRAM_CAPTION_LIMIT = 1024


def truncate_text(text: str, limit: int, *, footer: str = "") -> str:
    """Truncate text so that text + footer fit within limit."""
    if not footer:
        if len(text) <= limit:
            return text
        return text[: max(0, limit - 1)].rstrip() + "…"
    separator = "\n\n" if text else ""
    reserved = len(separator) + len(footer)
    if reserved >= limit:
        return footer[:limit]
    body_limit = limit - reserved
    body = text if len(text) <= body_limit else text[: max(0, body_limit - 1)].rstrip() + "…"
    if not body:
        return footer
    return f"{body}{separator}{footer}"


def normalize_for_hash(text: str) -> str:
    collapsed = re.sub(r"\s+", " ", text or "").strip().lower()
    return collapsed


def content_fingerprint(
    text: str,
    *,
    media_keys: list[str] | None = None,
) -> str:
    payload = normalize_for_hash(text)
    if media_keys:
        payload += "|" + "|".join(sorted(media_keys))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def collapse_blank_lines(text: str) -> str:
    text = re.sub(r"[ \t]+\n", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    text = re.sub(r"[ \t]{2,}", " ", text)
    return text.strip()
