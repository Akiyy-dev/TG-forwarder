"""Retry classification and backoff helpers."""

from __future__ import annotations

import asyncio
import random
from enum import StrEnum
from typing import Any


class RetryClass(StrEnum):
    RETRYABLE = "retryable"
    FATAL = "fatal"
    WAIT = "wait"


_RETRYABLE_NAMES = {
    "TelegramNetworkError",
    "TelegramServerError",
    "NetworkError",
    "ClientConnectorError",
    "TimedOut",
    "RestartingTelegram",
    "RetryAfter",
    "TelegramRetryAfter",
    "FloodWaitError",
    "TimeoutError",
    "asyncio.TimeoutError",
    "ServerError",
}

_FATAL_NAMES = {
    "TelegramForbiddenError",
    "TelegramBadRequest",
    "TelegramUnauthorizedError",
    "TelegramNotFound",
    "ChatWriteForbiddenError",
    "ChannelPrivateError",
    "UserBannedInChannelError",
    "MessageIdInvalidError",
    "BotMethodInvalidError",
}


def classify_exception(exc: BaseException) -> RetryClass:
    name = type(exc).__name__
    # aiogram RetryAfter
    if name in {"TelegramRetryAfter", "RetryAfter", "FloodWaitError"}:
        return RetryClass.WAIT
    if name in _FATAL_NAMES or "Forbidden" in name or "BadRequest" in name:
        return RetryClass.FATAL
    if name in _RETRYABLE_NAMES or "Network" in name or "Timeout" in name or "Server" in name:
        return RetryClass.RETRYABLE
    # Default conservative: retryable for unknown IO issues
    if isinstance(exc, (TimeoutError, ConnectionError, OSError)):
        return RetryClass.RETRYABLE
    return RetryClass.FATAL


def extract_wait_seconds(exc: BaseException) -> float | None:
    for attr in ("retry_after", "seconds", "value"):
        value = getattr(exc, attr, None)
        if value is not None:
            try:
                return float(value)
            except (TypeError, ValueError):
                continue
    return None


def compute_backoff(attempt: int, base_delay: float, *, jitter: bool = True) -> float:
    delay = base_delay * (2 ** max(0, attempt - 1))
    if jitter:
        delay += random.uniform(0, base_delay)
    return float(min(delay, 300.0))


async def sleep_for_retry(exc: BaseException, attempt: int, base_delay: float) -> RetryClass:
    kind = classify_exception(exc)
    if kind == RetryClass.WAIT:
        wait = extract_wait_seconds(exc) or compute_backoff(attempt, base_delay)
        await asyncio.sleep(wait + 0.5)
        return kind
    if kind == RetryClass.RETRYABLE:
        await asyncio.sleep(compute_backoff(attempt, base_delay))
        return kind
    return kind


def should_retry(exc: BaseException, attempt: int, max_retries: int) -> bool:
    if attempt >= max_retries:
        return False
    return classify_exception(exc) in {RetryClass.RETRYABLE, RetryClass.WAIT}


def exception_summary(exc: BaseException) -> dict[str, Any]:
    return {
        "exception_type": type(exc).__name__,
        "message": str(exc)[:500],
        "retry_class": classify_exception(exc).value,
    }
