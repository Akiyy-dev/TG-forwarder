"""Health check for local or server use. Exit 0 on success."""

from __future__ import annotations

import asyncio
import os
from pathlib import Path

from dotenv import load_dotenv


async def _check() -> int:
    load_dotenv()
    errors: list[str] = []

    # DB
    database_url = os.environ.get("DATABASE_URL", "sqlite+aiosqlite:///./data/database/app.db")
    try:
        from sqlalchemy import text
        from sqlalchemy.ext.asyncio import create_async_engine

        engine = create_async_engine(database_url)
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
        await engine.dispose()
    except Exception as exc:
        errors.append(f"database: {type(exc).__name__}")

    # Session file
    session_path = os.environ.get("TELEGRAM_SESSION_PATH", "./data/sessions/listener")
    session_file = Path(f"{session_path}.session")
    if not session_file.exists():
        errors.append("session_file_missing")
    else:
        try:
            from telethon import TelegramClient

            api_id = int(os.environ["TELEGRAM_API_ID"])
            api_hash = os.environ["TELEGRAM_API_HASH"]
            client = TelegramClient(session_path, api_id, api_hash)
            await client.connect()
            if not await client.is_user_authorized():
                errors.append("session_not_authorized")
            await client.disconnect()
        except Exception as exc:
            errors.append(f"session_check: {type(exc).__name__}")

    # Bot token
    bot_token = os.environ.get("BOT_TOKEN")
    target = os.environ.get("TARGET_CHANNEL_ID")
    if not bot_token:
        errors.append("bot_token_missing")
    else:
        try:
            from aiogram import Bot

            bot = Bot(token=bot_token)
            me = await bot.get_me()
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
            await bot.session.close()
        except Exception as exc:
            errors.append(f"bot_check: {type(exc).__name__}")

    # Download dir writable
    download_dir = Path(os.environ.get("DOWNLOAD_DIR", "./data/downloads"))
    try:
        download_dir.mkdir(parents=True, exist_ok=True)
        probe = download_dir / ".healthwrite"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink(missing_ok=True)
    except Exception:
        errors.append("download_dir_not_writable")

    if errors:
        print("UNHEALTHY:", ", ".join(errors))
        return 1
    print("OK")
    return 0


def main() -> None:
    raise SystemExit(asyncio.run(_check()))


if __name__ == "__main__":
    main()
