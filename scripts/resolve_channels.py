"""List/resolve channels and check bot publish rights (no secrets printed)."""

from __future__ import annotations

import asyncio
import os

from aiogram import Bot
from app.services.channel_service import parse_channel_ref
from dotenv import load_dotenv
from telethon import TelegramClient
from telethon.tl.types import Channel, Chat, User


async def _run() -> int:
    load_dotenv()
    api_id = int(os.environ["TELEGRAM_API_ID"])
    api_hash = os.environ["TELEGRAM_API_HASH"]
    session_path = os.environ.get("TELEGRAM_SESSION_PATH", "./data/sessions/listener")
    bot_token = os.environ.get("BOT_TOKEN", "")
    target = os.environ.get("TARGET_CHANNEL_ID", "")
    sources = [s.strip() for s in os.environ.get("SOURCE_CHANNELS", "").split(",") if s.strip()]

    client = TelegramClient(session_path, api_id, api_hash)
    await client.connect()
    if not await client.is_user_authorized():
        print("ERROR: session not authorized. Run: python -m scripts.create_session")
        await client.disconnect()
        return 1

    print("=== Dialogs (channels) available to listener account ===")
    async for dialog in client.iter_dialogs():
        entity = dialog.entity
        if isinstance(entity, Channel) and getattr(entity, "broadcast", False):
            cid = int(entity.id)
            full = int(f"-100{cid}") if cid > 0 else cid
            print(f"title={dialog.name!r} username={getattr(entity, 'username', None)} id={full}")

    print("\n=== Resolve SOURCE_CHANNELS ===")
    env_ids: list[str] = []
    for ref in sources:
        try:
            entity = await client.get_entity(parse_channel_ref(ref))
        except Exception as exc:
            print(f"FAIL {ref}: {type(exc).__name__}")
            continue
        if isinstance(entity, User):
            print(f"SKIP {ref}: is a user, not a channel")
            continue
        if isinstance(entity, Chat):
            print(f"WARN {ref}: basic group, not a channel")
        cid = int(entity.id)
        full = int(f"-100{cid}") if isinstance(entity, Channel) and cid > 0 else cid
        print(
            f"OK {ref} -> id={full} username={getattr(entity, 'username', None)} "
            f"title={getattr(entity, 'title', None)}"
        )
        env_ids.append(str(full))

        # readability check: try get messages
        try:
            msgs = await client.get_messages(entity, limit=1)
            print(f"  readable=yes last_message_id={msgs[0].id if msgs else None}")
        except Exception as exc:
            print(f"  readable=no error={type(exc).__name__}")

    if env_ids:
        print("\nSuggested SOURCE_CHANNELS=")
        print(",".join(env_ids))

    if bot_token and target:
        print("\n=== Bot target channel access ===")
        bot = Bot(token=bot_token)
        try:
            chat = await bot.get_chat(int(target))
            member = await bot.get_chat_member(int(target), (await bot.get_me()).id)
            can_post = bool(
                getattr(member, "can_post_messages", False) or member.status == "administrator"
            )
            print(
                f"target_title={getattr(chat, 'title', None)} "
                f"bot_status={member.status} can_post={can_post}"
            )
        except Exception as exc:
            print(f"Bot target check failed: {type(exc).__name__}")
        finally:
            await bot.session.close()

    await client.disconnect()
    return 0


def main() -> None:
    raise SystemExit(asyncio.run(_run()))


if __name__ == "__main__":
    main()
