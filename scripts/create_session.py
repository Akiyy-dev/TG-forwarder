"""Interactive Telethon session creation (run once before deploying)."""

from __future__ import annotations

import asyncio
import contextlib
import os
import stat
from pathlib import Path

from app.utils.files import ensure_dir
from dotenv import load_dotenv
from telethon import TelegramClient
from telethon.errors import SessionPasswordNeededError


async def _create() -> None:
    load_dotenv()
    api_id = int(os.environ["TELEGRAM_API_ID"])
    api_hash = os.environ["TELEGRAM_API_HASH"]
    phone = os.environ.get("TELEGRAM_PHONE") or input("Phone (+countrycode): ").strip()
    session_path = os.environ.get("TELEGRAM_SESSION_PATH", "./data/sessions/listener")
    ensure_dir(Path(session_path).parent)

    client = TelegramClient(session_path, api_id, api_hash)
    await client.connect()
    if await client.is_user_authorized():
        print("Session already authorized.")
        me = await client.get_me()
        print(f"Logged in as: {getattr(me, 'username', None) or me.id}")
        await client.disconnect()
        return

    await client.send_code_request(phone)
    code = input("Telegram login code: ").strip()
    try:
        await client.sign_in(phone=phone, code=code)
    except SessionPasswordNeededError:
        password = input("Two-step verification password: ").strip()
        await client.sign_in(password=password)

    me = await client.get_me()
    print(f"Session created for: {getattr(me, 'username', None) or me.id}")
    await client.disconnect()

    # Restrict permissions when possible (Unix)
    for suffix in ("", ".session"):
        path = Path(f"{session_path}{suffix}" if suffix else f"{session_path}.session")
        if path.exists():
            with contextlib.suppress(OSError):
                os.chmod(path, stat.S_IRUSR | stat.S_IWUSR)
    print(f"Session file saved under: {session_path}.session")
    print("Do NOT commit this file. Keep the data/sessions volume persisted.")


def main() -> None:
    asyncio.run(_create())


if __name__ == "__main__":
    main()
