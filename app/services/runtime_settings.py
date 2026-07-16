"""Runtime settings persisted to config/runtime.yaml (non-secret hot config)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from app.logging import get_logger

logger = get_logger(__name__)

RUNTIME_PATH = Path("./config/runtime.yaml")

# Field metadata: default value + how change must be applied.
FIELD_META: dict[str, dict[str, Any]] = {
    "review_auto_publish_seconds": {"default": 10, "apply": "hot", "group": "review"},
    "review_auto_approve_enabled": {"default": True, "apply": "hot", "group": "review"},
    "review_auto_approve_minutes": {"default": 10, "apply": "hot", "group": "review"},
    "history_enabled": {"default": False, "apply": "hot", "group": "history"},
    "history_max_per_source": {"default": 100, "apply": "hot", "group": "history"},
    "history_dir": {"default": "./data/history", "apply": "hot", "group": "history"},
    "album_wait_seconds": {"default": None, "apply": "hot", "group": "listener"},
    "temp_file_ttl_minutes": {"default": None, "apply": "hot", "group": "listener"},
    "message_footer": {"default": None, "apply": "hot", "group": "processors"},
    "enable_keyword_filter": {"default": None, "apply": "hot", "group": "processors"},
    "enable_text_replace": {"default": None, "apply": "hot", "group": "processors"},
    "enable_link_filter": {"default": None, "apply": "hot", "group": "processors"},
    "enable_footer": {"default": None, "apply": "hot", "group": "processors"},
    "enable_duplicate_filter": {"default": None, "apply": "hot", "group": "processors"},
    "web_host": {"default": None, "apply": "restart", "group": "web"},
    "web_port": {"default": None, "apply": "restart", "group": "web"},
    "database_url": {"default": None, "apply": "restart", "group": "basic"},
    "bot_token": {"default": None, "apply": "restart", "group": "basic", "secret": True},
    "telegram_api_id": {"default": None, "apply": "restart", "group": "basic", "secret": True},
    "telegram_api_hash": {"default": None, "apply": "restart", "group": "basic", "secret": True},
}


class RuntimeSettings:
    def __init__(self, path: Path | str = RUNTIME_PATH) -> None:
        self.path = Path(path)
        self._data: dict[str, Any] = {}
        self.load()

    def load(self) -> None:
        if not self.path.is_file():
            self._data = {}
            return
        raw = yaml.safe_load(self.path.read_text(encoding="utf-8")) or {}
        self._data = raw if isinstance(raw, dict) else {}

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(
            yaml.safe_dump(self._data, allow_unicode=True, sort_keys=True),
            encoding="utf-8",
        )

    def get(self, key: str, default: Any = None) -> Any:
        if key in self._data:
            return self._data[key]
        meta = FIELD_META.get(key) or {}
        if meta.get("default") is not None:
            return meta["default"]
        return default

    def update(self, patch: dict[str, Any]) -> dict[str, Any]:
        """Apply patch of writable non-secret fields. Returns apply severities used."""
        applies: set[str] = set()
        for key, value in patch.items():
            meta = FIELD_META.get(key)
            if meta is None:
                continue
            if meta.get("secret"):
                continue
            self._data[key] = value
            applies.add(str(meta.get("apply") or "hot"))
        self.save()
        severity = "hot"
        if "restart" in applies:
            severity = "restart"
        elif "reload_listener" in applies:
            severity = "reload_listener"
        return {"apply": severity, "fields": list(patch.keys())}

    def export_for_api(self, settings: Any) -> dict[str, Any]:
        """Build settings response with values, apply hints, and masked secrets."""
        groups: dict[str, list[dict[str, Any]]] = {}
        for key, meta in FIELD_META.items():
            group = str(meta.get("group") or "basic")
            value = self.get(key)
            if value is None and hasattr(settings, key):
                value = getattr(settings, key)
            if meta.get("secret") and value:
                text = str(value)
                value = text[:4] + "…" if len(text) > 4 else "••••"
            groups.setdefault(group, []).append(
                {
                    "key": key,
                    "value": value,
                    "apply": meta.get("apply", "hot"),
                    "secret": bool(meta.get("secret")),
                    "readonly": bool(meta.get("secret")),
                }
            )
        return {
            "groups": groups,
            "values": {
                k: self.get(k) if not FIELD_META[k].get("secret") else None
                for k in FIELD_META
                if not FIELD_META[k].get("secret")
            },
        }


_runtime: RuntimeSettings | None = None


def get_runtime_settings() -> RuntimeSettings:
    global _runtime
    if _runtime is None:
        _runtime = RuntimeSettings()
    return _runtime
