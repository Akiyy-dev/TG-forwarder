"""Shared lifecycle helpers for process entrypoints."""

from __future__ import annotations

import asyncio
import signal
from typing import Any

from app.logging import get_logger

logger = get_logger(__name__)


def install_shutdown_handlers(stop_event: asyncio.Event) -> None:
    def request_stop(*_args: Any) -> None:
        logger.info("shutdown_signal")
        stop_event.set()

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, request_stop)
        except NotImplementedError:
            signal.signal(sig, request_stop)


class UnavailablePublisher:
    """Web-role placeholder that prevents accidental direct publishing."""

    async def publish(self, *_args: Any, **_kwargs: Any) -> list[int]:
        raise RuntimeError("Telegram publishing is only available in the sender container")
