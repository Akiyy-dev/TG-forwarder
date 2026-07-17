"""Redis Streams transport with consumer groups and explicit acknowledgements."""

from __future__ import annotations

import asyncio
import contextlib
from collections.abc import Awaitable, Callable
from typing import Any

from redis.asyncio import Redis
from redis.exceptions import ResponseError
from redis.typing import EncodableT

from app.config import Settings
from app.logging import get_logger
from app.messaging.models import CommandEvent, IncomingMessageEvent, SourceBackend
from app.schemas.message import NormalizedMessage

logger = get_logger(__name__)

IncomingHandler = Callable[[IncomingMessageEvent], Awaitable[None]]
CommandHandler = Callable[[CommandEvent], Awaitable[None]]


class RedisStreamBus:
    """Small transport boundary shared by all four application containers."""

    def __init__(self, settings: Settings, *, consumer_name: str | None = None) -> None:
        self.settings = settings
        self.consumer_name = consumer_name or settings.redis_consumer_name
        self.redis: Redis = Redis.from_url(settings.redis_url, decode_responses=True)

    async def ping(self) -> bool:
        return bool(await self.redis.ping())

    async def close(self) -> None:
        await self.redis.aclose()

    async def heartbeat_loop(
        self,
        role: str,
        stop_event: asyncio.Event,
        *,
        health_probe: Callable[[], bool] | None = None,
    ) -> None:
        key = f"forwarder:heartbeat:{role}"
        while not stop_event.is_set():
            try:
                healthy = health_probe is None or health_probe()
                if healthy:
                    await self.redis.set(key, "1", ex=15)
                else:
                    # Do not leave a fresh role heartbeat behind when the process that
                    # the container is supervising (for example, a GUI bridge) is down.
                    await self.redis.delete(key)
            except Exception:
                logger.exception("heartbeat_failed", role=role)
            with contextlib.suppress(TimeoutError):
                await asyncio.wait_for(stop_event.wait(), timeout=5)

    async def role_alive(self, role: str) -> bool:
        try:
            return bool(await self.redis.exists(f"forwarder:heartbeat:{role}"))
        except Exception:
            logger.warning("heartbeat_read_failed", role=role)
            return False

    async def incoming_queue_size(self) -> int | None:
        """Return the shared incoming stream length, or ``None`` when unavailable.

        Consumed entries are deleted by the sender, so XLEN represents messages that
        have not completed handling. Returning ``None`` keeps Redis failures distinct
        from a genuinely empty queue.
        """

        try:
            return int(await self.redis.xlen(self.settings.redis_incoming_stream))
        except Exception:
            logger.warning(
                "incoming_queue_size_read_failed",
                stream=self.settings.redis_incoming_stream,
                exc_info=True,
            )
            return None

    async def publish_incoming(self, backend: SourceBackend, message: NormalizedMessage) -> str:
        event = IncomingMessageEvent.create(backend, message)
        fields: dict[EncodableT, EncodableT] = {"payload": event.to_json()}
        if self.settings.redis_stream_maxlen > 0:
            result = await self.redis.xadd(
                self.settings.redis_incoming_stream,
                fields,
                maxlen=self.settings.redis_stream_maxlen,
                approximate=True,
            )
        else:
            result = await self.redis.xadd(self.settings.redis_incoming_stream, fields)
        logger.info(
            "incoming_event_published",
            event_id=event.event_id,
            backend=backend,
            source_chat_id=message.source_chat_id,
            source_message_id=message.source_message_id,
        )
        return str(result)

    async def publish_command(self, kind: str, payload: dict[str, Any] | None = None) -> str:
        event = CommandEvent.create(kind, payload)
        fields: dict[EncodableT, EncodableT] = {"payload": event.to_json()}
        if self.settings.redis_stream_maxlen > 0:
            result = await self.redis.xadd(
                self.settings.redis_command_stream,
                fields,
                maxlen=self.settings.redis_stream_maxlen,
                approximate=True,
            )
        else:
            result = await self.redis.xadd(self.settings.redis_command_stream, fields)
        logger.info("command_event_published", event_id=event.event_id, kind=kind)
        return str(result)

    async def _ensure_group(self, stream: str) -> None:
        try:
            await self.redis.xgroup_create(
                stream,
                self.settings.redis_sender_group,
                id="0-0",
                mkstream=True,
            )
        except ResponseError as exc:
            if "BUSYGROUP" not in str(exc):
                raise

    async def _claimed_entries(self, stream: str) -> list[tuple[str, dict[str, str]]]:
        claimed = await self.redis.xautoclaim(
            stream,
            self.settings.redis_sender_group,
            self.consumer_name,
            min_idle_time=self.settings.redis_claim_idle_ms,
            start_id="0-0",
            count=20,
        )
        if not claimed or len(claimed) < 2:
            return []
        return list(claimed[1])

    async def _new_entries(self, stream: str) -> list[tuple[str, dict[str, str]]]:
        rows = await self.redis.xreadgroup(
            self.settings.redis_sender_group,
            self.consumer_name,
            {stream: ">"},
            count=20,
            block=self.settings.redis_block_ms,
        )
        if not rows:
            return []
        return list(rows[0][1])

    async def _consume(
        self,
        stream: str,
        decode: Callable[[str], Any],
        handler: Callable[[Any], Awaitable[None]],
        stop_event: asyncio.Event,
    ) -> None:
        await self._ensure_group(stream)
        while not stop_event.is_set():
            try:
                entries = await self._claimed_entries(stream)
                if not entries:
                    entries = await self._new_entries(stream)
                for redis_id, fields in entries:
                    try:
                        event = decode(fields["payload"])
                    except Exception:
                        logger.exception("stream_event_decode_failed", stream=stream)
                        await self.redis.xack(stream, self.settings.redis_sender_group, redis_id)
                        # The payload can never be handled successfully. Remove it after
                        # acknowledging so stream length continues to reflect actionable
                        # incoming work instead of accumulating poison events forever.
                        await self.redis.xdel(stream, redis_id)
                        continue
                    while not stop_event.is_set():
                        try:
                            await handler(event)
                            break
                        except Exception:
                            logger.exception(
                                "stream_event_handler_failed",
                                stream=stream,
                                redis_id=redis_id,
                            )
                            with contextlib.suppress(TimeoutError):
                                await asyncio.wait_for(stop_event.wait(), timeout=2)
                    if stop_event.is_set():
                        return
                    await self.redis.xack(stream, self.settings.redis_sender_group, redis_id)
                    await self.redis.xdel(stream, redis_id)
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("stream_consumer_error", stream=stream)
                with contextlib.suppress(TimeoutError):
                    await asyncio.wait_for(stop_event.wait(), timeout=2)

    async def consume_incoming(self, handler: IncomingHandler, stop_event: asyncio.Event) -> None:
        await self._consume(
            self.settings.redis_incoming_stream,
            IncomingMessageEvent.from_json,
            handler,
            stop_event,
        )

    async def consume_commands(self, handler: CommandHandler, stop_event: asyncio.Event) -> None:
        await self._consume(
            self.settings.redis_command_stream,
            CommandEvent.from_json,
            handler,
            stop_event,
        )
