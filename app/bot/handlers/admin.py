"""Admin management commands."""

from __future__ import annotations

from typing import Any

from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message

from app.bot.middlewares import require_admin

router = Router(name="admin")


@router.message(Command("start"))
async def cmd_start(message: Message, is_admin: bool = False) -> None:
    denial = require_admin(is_admin)
    if denial:
        await message.answer(denial)
        return
    await message.answer("TG-forwarder is online. Use /help for commands.")


@router.message(Command("help"))
async def cmd_help(message: Message, is_admin: bool = False) -> None:
    denial = require_admin(is_admin)
    if denial:
        await message.answer(denial)
        return
    text = (
        "Commands:\n"
        "/status - runtime status\n"
        "/sources - source channels\n"
        "/stats - message counters\n"
        "/retry_failed - retry failed jobs\n"
        "/pause - pause publishing\n"
        "/resume - resume publishing\n"
        "/help - this message"
    )
    await message.answer(text)


@router.message(Command("status"))
async def cmd_status(
    message: Message,
    message_service: Any,
    listener: Any = None,
    is_admin: bool = False,
) -> None:
    denial = require_admin(is_admin)
    if denial:
        await message.answer(denial)
        return
    paused = await message_service.refresh_paused()
    listener_ok = bool(listener and getattr(listener, "is_connected", False))
    lines = [
        "Status:",
        f"- listener: {'ok' if listener_ok else 'down'}",
        f"- publishing: {'paused' if paused else 'active'}",
        f"- queue: {message_service.queue_size}",
        f"- last_error: {message_service.last_error or '-'}",
    ]
    if listener and getattr(listener, "last_error", None):
        lines.append(f"- listener_error: {listener.last_error}")
    await message.answer("\n".join(lines))


@router.message(Command("sources"))
async def cmd_sources(
    message: Message,
    channel_service: Any,
    is_admin: bool = False,
) -> None:
    denial = require_admin(is_admin)
    if denial:
        await message.answer(denial)
        return
    sources = await channel_service.list_sources()
    if not sources:
        await message.answer("No source channels configured.")
        return
    lines = ["Sources:"]
    for src in sources:
        uname = f"@{src.username}" if src.username else "-"
        lines.append(f"- {src.chat_id} {uname} enabled={src.enabled} title={src.title or '-'}")
    await message.answer("\n".join(lines))


@router.message(Command("stats"))
async def cmd_stats(
    message: Message,
    message_service: Any,
    is_admin: bool = False,
) -> None:
    denial = require_admin(is_admin)
    if denial:
        await message.answer(denial)
        return
    stats = await message_service.stats()
    received = sum(stats.values())
    lines = [
        "Stats:",
        f"- received_total_rows: {received}",
        f"- filtered: {stats.get('filtered', 0)}",
        f"- published: {stats.get('published', 0)}",
        f"- failed: {stats.get('failed', 0)}",
        f"- retrying: {stats.get('retrying', 0)}",
        f"- pending_publish: {stats.get('pending_publish', 0)}",
    ]
    await message.answer("\n".join(lines))


@router.message(Command("retry_failed"))
async def cmd_retry_failed(
    message: Message,
    message_service: Any,
    is_admin: bool = False,
) -> None:
    denial = require_admin(is_admin)
    if denial:
        await message.answer(denial)
        return
    count = await message_service.retry_failed()
    await message.answer(f"Re-queued {count} failed/retrying jobs.")


@router.message(Command("pause"))
async def cmd_pause(
    message: Message,
    message_service: Any,
    is_admin: bool = False,
) -> None:
    denial = require_admin(is_admin)
    if denial:
        await message.answer(denial)
        return
    await message_service.set_paused(True)
    await message.answer("Publishing paused. Incoming messages are still recorded.")


@router.message(Command("resume"))
async def cmd_resume(
    message: Message,
    message_service: Any,
    is_admin: bool = False,
) -> None:
    denial = require_admin(is_admin)
    if denial:
        await message.answer(denial)
        return
    requeued = await message_service.resume_publishing()
    await message.answer(f"Publishing resumed. Requeued {requeued} message(s).")
