"""Optional history JSON persistence for processed messages."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from app.logging import get_logger
from app.services.runtime_settings import get_runtime_settings

logger = get_logger(__name__)


class HistoryService:
    def write(
        self,
        *,
        source_chat_id: int,
        source_message_id: int,
        payload: dict[str, Any],
    ) -> Path | None:
        runtime = get_runtime_settings()
        if not bool(runtime.get("history_enabled", False)):
            return None
        base = Path(str(runtime.get("history_dir", "./data/history")))
        directory = base / str(source_chat_id)
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / f"{source_message_id}.json"
        data = {
            **payload,
            "source_chat_id": source_chat_id,
            "source_message_id": source_message_id,
            "saved_at": datetime.now(UTC).isoformat(),
        }
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        logger.debug(
            "history_written",
            source_chat_id=source_chat_id,
            source_message_id=source_message_id,
            path=str(path),
        )
        self.prune_source(source_chat_id)
        return path

    def prune_source(self, source_chat_id: int) -> int:
        runtime = get_runtime_settings()
        limit = int(runtime.get("history_max_per_source", 100) or 100)
        base = Path(str(runtime.get("history_dir", "./data/history")))
        directory = base / str(source_chat_id)
        if not directory.is_dir():
            return 0
        files = sorted(
            [p for p in directory.glob("*.json") if p.is_file()],
            key=lambda p: p.stat().st_mtime,
        )
        removed = 0
        while len(files) > limit:
            files.pop(0).unlink(missing_ok=True)
            removed += 1
        return removed

    def prune_all(self) -> int:
        runtime = get_runtime_settings()
        base = Path(str(runtime.get("history_dir", "./data/history")))
        if not base.is_dir():
            return 0
        total = 0
        for child in base.iterdir():
            if child.is_dir() and child.name.lstrip("-").isdigit():
                total += self.prune_source(int(child.name))
        return total
