"""Shared service-status helpers for monolithic and distributed deployments."""

from __future__ import annotations

from typing import Literal, TypedDict

from app.context import AppContext


class QueueStatus(TypedDict):
    queue_size: int | None
    queue_size_available: bool
    queue_size_source: Literal["process_memory", "redis_stream"]


async def queue_status(ctx: AppContext) -> QueueStatus:
    """Read queue state from the process that owns it in the active architecture."""

    if ctx.command_bus is None:
        return {
            "queue_size": ctx.message_service.queue_size,
            "queue_size_available": True,
            "queue_size_source": "process_memory",
        }

    size = await ctx.command_bus.incoming_queue_size()
    return {
        "queue_size": size,
        "queue_size_available": size is not None,
        "queue_size_source": "redis_stream",
    }
