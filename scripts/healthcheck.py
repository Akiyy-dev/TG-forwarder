"""Role-aware health check for local or server use. Exit 0 on success."""

from __future__ import annotations

import asyncio
import contextlib
import os
from pathlib import Path

from dotenv import load_dotenv

CheckName = str

# ``all`` is the legacy single-process entry point and deliberately does not
# require Redis. The distributed entry points use Redis for transport.
_ROLE_CHECKS: dict[str, tuple[CheckName, ...]] = {
    "all": ("database", "telegram_session", "bot", "download_dir"),
    "web": ("database", "redis", "download_dir"),
    "sender": ("database", "redis", "bot", "download_dir"),
    "telegram-receiver": ("database", "redis", "telegram_session", "download_dir"),
    "safew-receiver": ("redis",),
    "migrate": ("database",),
}


def _checks_for_role(role: str) -> tuple[CheckName, ...] | None:
    return _ROLE_CHECKS.get(role.strip().lower())


async def _check_database() -> list[str]:
    database_url = os.environ.get("DATABASE_URL", "sqlite+aiosqlite:///./data/database/app.db")
    engine = None
    try:
        from sqlalchemy import text
        from sqlalchemy.ext.asyncio import create_async_engine

        engine = create_async_engine(database_url)
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
    except Exception as exc:
        return [f"database: {type(exc).__name__}"]
    finally:
        if engine is not None:
            with contextlib.suppress(Exception):
                await engine.dispose()
    return []


async def _check_redis() -> list[str]:
    redis_url = os.environ.get("REDIS_URL", "redis://redis:6379/0")
    client = None
    try:
        from redis.asyncio import Redis

        client = Redis.from_url(redis_url, decode_responses=True)
        if not await client.ping():
            return ["redis_ping_failed"]
    except Exception as exc:
        return [f"redis: {type(exc).__name__}"]
    finally:
        if client is not None:
            with contextlib.suppress(Exception):
                await client.aclose()
    return []


async def _check_telegram_session() -> list[str]:
    session_path = os.environ.get("TELEGRAM_SESSION_PATH", "./data/sessions/listener")
    session_file = Path(f"{session_path}.session")
    if not session_file.exists():
        return ["session_file_missing"]

    api_id = os.environ.get("TELEGRAM_API_ID")
    api_hash = os.environ.get("TELEGRAM_API_HASH")
    if not api_id or not api_hash:
        return ["telegram_credentials_missing"]

    client = None
    try:
        from telethon import TelegramClient

        client = TelegramClient(session_path, int(api_id), api_hash)
        await client.connect()
        if not await client.is_user_authorized():
            return ["session_not_authorized"]
    except Exception as exc:
        return [f"session_check: {type(exc).__name__}"]
    finally:
        if client is not None:
            with contextlib.suppress(Exception):
                await client.disconnect()
    return []


async def _check_bot() -> list[str]:
    bot_token = os.environ.get("BOT_TOKEN")
    target = os.environ.get("TARGET_CHANNEL_ID")
    if not bot_token:
        return ["bot_token_missing"]

    bot = None
    try:
        from aiogram import Bot

        bot = Bot(token=bot_token)
        me = await bot.get_me()
        errors: list[str] = []
        if not me.username:
            errors.append("bot_invalid")
        if target:
            try:
                member = await bot.get_chat_member(int(target), me.id)
                status = getattr(member, "status", None)
                if status not in {"administrator", "creator"}:
                    errors.append("bot_not_admin_in_target")
            except Exception:
                errors.append("bot_cannot_access_target")
        return errors
    except Exception as exc:
        return [f"bot_check: {type(exc).__name__}"]
    finally:
        if bot is not None:
            with contextlib.suppress(Exception):
                await bot.session.close()


async def _check_download_dir() -> list[str]:
    download_dir = Path(os.environ.get("DOWNLOAD_DIR", "./data/downloads"))
    try:
        download_dir.mkdir(parents=True, exist_ok=True)
        probe = download_dir / ".healthwrite"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink(missing_ok=True)
    except Exception:
        return ["download_dir_not_writable"]
    return []


async def _check() -> int:
    load_dotenv()
    role = os.environ.get("APP_ROLE", "all").strip().lower() or "all"
    selected = _checks_for_role(role)
    if selected is None:
        print(f"UNHEALTHY: unsupported_app_role: {role}")
        return 1

    errors: list[str] = []
    if "database" in selected:
        errors.extend(await _check_database())
    if "redis" in selected:
        errors.extend(await _check_redis())
    if "telegram_session" in selected:
        errors.extend(await _check_telegram_session())
    if "bot" in selected:
        errors.extend(await _check_bot())
    if "download_dir" in selected:
        errors.extend(await _check_download_dir())

    if errors:
        print("UNHEALTHY:", ", ".join(errors))
        return 1
    print("OK")
    return 0


def main() -> None:
    raise SystemExit(asyncio.run(_check()))


if __name__ == "__main__":
    main()
