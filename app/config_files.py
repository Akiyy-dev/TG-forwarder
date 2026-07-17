"""Load rule seed config files (YAML)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from app.logging import get_logger

logger = get_logger(__name__)


def load_yaml_file(path: str | Path) -> Any:
    file_path = Path(path)
    if not file_path.is_file():
        return None
    text = file_path.read_text(encoding="utf-8")
    if not text.strip():
        return None
    return yaml.safe_load(text)


def load_rules_config(path: str | Path) -> list[dict[str, Any]]:
    """Return list of rule seed entries from YAML."""
    data = load_yaml_file(path)
    if data is None:
        return []
    if isinstance(data, dict):
        items = data.get("rules") or data.get("items") or []
    elif isinstance(data, list):
        items = data
    else:
        return []
    return [item for item in items if isinstance(item, dict)]
