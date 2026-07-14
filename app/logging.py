"""Structured logging setup with sensitive-data redaction."""

from __future__ import annotations

import logging
import re
import sys
from collections.abc import Mapping, MutableMapping
from typing import Any, cast

import structlog

_SENSITIVE_KEYS = frozenset(
    {
        "bot_token",
        "token",
        "api_hash",
        "telegram_api_hash",
        "password",
        "code",
        "phone",
        "telegram_phone",
        "session",
        "session_string",
        "authorization",
    }
)

_TOKEN_RE = re.compile(r"\b\d{6,}:[A-Za-z0-9_-]{20,}\b")
_HASH_RE = re.compile(r"\b[a-f0-9]{32}\b", re.IGNORECASE)


def _redact_value(key: str, value: Any) -> Any:
    lowered = key.lower()
    if lowered in _SENSITIVE_KEYS or any(s in lowered for s in _SENSITIVE_KEYS):
        return "***"
    if isinstance(value, str):
        redacted = _TOKEN_RE.sub("***", value)
        if "hash" in lowered or "api" in lowered:
            redacted = _HASH_RE.sub("***", redacted)
        return redacted
    return value


def redact_processor(
    _logger: Any,
    _method_name: str,
    event_dict: MutableMapping[str, Any],
) -> Mapping[str, Any]:
    return {key: _redact_value(key, value) for key, value in event_dict.items()}


def setup_logging(level: str = "INFO", json_logs: bool = True) -> None:
    """Configure structlog and stdlib logging for stdout."""
    log_level = getattr(logging, level.upper(), logging.INFO)

    shared_processors: list[structlog.types.Processor] = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_log_level,
        structlog.stdlib.add_logger_name,
        structlog.processors.TimeStamper(fmt="iso", utc=True),
        structlog.processors.StackInfoRenderer(),
        redact_processor,
        structlog.processors.format_exc_info,
    ]

    if json_logs:
        renderer: structlog.types.Processor = structlog.processors.JSONRenderer()
    else:
        renderer = structlog.dev.ConsoleRenderer()

    structlog.configure(
        processors=[
            *shared_processors,
            structlog.stdlib.ProcessorFormatter.wrap_for_formatter,
        ],
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=True,
    )

    formatter = structlog.stdlib.ProcessorFormatter(
        processors=[
            structlog.stdlib.ProcessorFormatter.remove_processors_meta,
            renderer,
        ],
    )

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(formatter)

    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(log_level)

    # Quiet noisy libraries
    logging.getLogger("telethon").setLevel(logging.WARNING)
    logging.getLogger("aiogram").setLevel(logging.INFO)


def get_logger(name: str | None = None) -> structlog.stdlib.BoundLogger:
    return cast(structlog.stdlib.BoundLogger, structlog.get_logger(name))
