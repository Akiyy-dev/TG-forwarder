"""Server-side Telegram publish preview (approximate)."""

from __future__ import annotations

from typing import Any

from app.database.models import ReviewTask
from app.schemas.message import MediaType
from app.utils.text import TELEGRAM_CAPTION_LIMIT, TELEGRAM_TEXT_LIMIT


def build_publish_preview(task: ReviewTask) -> dict[str, Any]:
    text = task.final_text or ""
    media_type = task.media_type or MediaType.TEXT.value
    is_text = media_type == MediaType.TEXT.value
    limit = TELEGRAM_TEXT_LIMIT if is_text else TELEGRAM_CAPTION_LIMIT
    truncated = len(text) > limit
    body = text if not truncated else text[: limit - 1] + "…"
    album_note = None
    if media_type == MediaType.ALBUM.value:
        album_note = "Caption attaches to the first media item in the album."
    split_plan: list[str] = []
    if is_text and len(text) > TELEGRAM_TEXT_LIMIT:
        remaining = text
        part = 1
        while remaining:
            chunk = remaining[:TELEGRAM_TEXT_LIMIT]
            split_plan.append(f"part-{part}: {len(chunk)} chars")
            remaining = remaining[TELEGRAM_TEXT_LIMIT:]
            part += 1
    return {
        "approximate": True,
        "disclaimer": "Preview approximates Telegram layout; client rendering may differ.",
        "target_chat_id": task.target_chat_id,
        "media_type": media_type,
        "media_count": task.media_count,
        "text": body,
        "text_length": len(text),
        "limit": limit,
        "truncated": truncated,
        "uses_caption": not is_text and bool(text),
        "album_caption_note": album_note,
        "split_plan": split_plan,
        "media_items": (task.media_snapshot or {}).get("media_items", [])
        if isinstance(task.media_snapshot, dict)
        else [],
    }
