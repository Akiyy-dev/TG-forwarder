"""Redis Streams status and heartbeat behavior tests."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

from app.config import Settings
from app.messaging.redis_streams import RedisStreamBus


def _bus_with_redis(settings: Settings) -> tuple[RedisStreamBus, MagicMock]:
    bus = RedisStreamBus(settings)
    redis = MagicMock()
    bus.redis = redis
    return bus, redis


async def test_incoming_queue_size_reads_shared_stream(settings_env: Settings) -> None:
    bus, redis = _bus_with_redis(settings_env)
    redis.xlen = AsyncMock(return_value=7)

    assert await bus.incoming_queue_size() == 7
    redis.xlen.assert_awaited_once_with(settings_env.redis_incoming_stream)


async def test_incoming_queue_size_is_unavailable_on_redis_error(settings_env: Settings) -> None:
    bus, redis = _bus_with_redis(settings_env)
    redis.xlen = AsyncMock(side_effect=ConnectionError("redis unavailable"))

    with patch("app.messaging.redis_streams.logger.warning") as warning:
        assert await bus.incoming_queue_size() is None

    warning.assert_called_once()


async def test_heartbeat_probe_removes_stale_role_key(settings_env: Settings) -> None:
    bus, redis = _bus_with_redis(settings_env)
    stop_event = asyncio.Event()

    async def delete_and_stop(_key: str) -> int:
        stop_event.set()
        return 1

    redis.delete = AsyncMock(side_effect=delete_and_stop)
    redis.set = AsyncMock()

    await bus.heartbeat_loop(
        "safew-receiver",
        stop_event,
        health_probe=lambda: False,
    )

    redis.delete.assert_awaited_once_with("forwarder:heartbeat:safew-receiver")
    redis.set.assert_not_awaited()


async def test_heartbeat_probe_renews_healthy_role_key(settings_env: Settings) -> None:
    bus, redis = _bus_with_redis(settings_env)
    stop_event = asyncio.Event()

    async def set_and_stop(_key: str, _value: str, *, ex: int) -> bool:
        stop_event.set()
        return ex == 15

    redis.set = AsyncMock(side_effect=set_and_stop)
    redis.delete = AsyncMock()

    await bus.heartbeat_loop("sender", stop_event, health_probe=lambda: True)

    redis.set.assert_awaited_once_with("forwarder:heartbeat:sender", "1", ex=15)
    redis.delete.assert_not_awaited()


async def test_decode_error_is_acknowledged_and_deleted(settings_env: Settings) -> None:
    bus, redis = _bus_with_redis(settings_env)
    stop_event = asyncio.Event()
    bus._ensure_group = AsyncMock()
    bus._claimed_entries = AsyncMock(return_value=[("1-0", {"payload": "broken"})])
    bus._new_entries = AsyncMock()
    redis.xack = AsyncMock()

    async def delete_and_stop(_stream: str, _redis_id: str) -> int:
        stop_event.set()
        return 1

    redis.xdel = AsyncMock(side_effect=delete_and_stop)
    decode = MagicMock(side_effect=ValueError("invalid payload"))
    handler = AsyncMock()

    await bus._consume("incoming", decode, handler, stop_event)

    redis.xack.assert_awaited_once_with("incoming", settings_env.redis_sender_group, "1-0")
    redis.xdel.assert_awaited_once_with("incoming", "1-0")
    handler.assert_not_awaited()
