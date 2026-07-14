"""Create or update a web admin user (interactive-safe)."""

from __future__ import annotations

import argparse
import asyncio
import getpass
import os
import sys

from app.auth.passwords import hash_password
from app.auth.roles import Role
from app.config import clear_settings_cache
from app.database.models import User
from app.database.session import dispose_engine, init_db
from dotenv import load_dotenv
from sqlalchemy import select


async def _run(username: str, password: str, role: str) -> int:
    load_dotenv()
    # Allow create_admin without full telegram config by temporarily relaxing via env for DB only
    database_url = os.environ.get("DATABASE_URL", "sqlite+aiosqlite:///./data/database/app.db")
    factory = await init_db(database_url)
    async with factory() as session:
        result = await session.execute(select(User).where(User.username == username))
        user = result.scalar_one_or_none()
        pwd_hash = hash_password(password)
        if user is None:
            session.add(
                User(
                    username=username,
                    password_hash=pwd_hash,
                    role=role,
                    is_active=True,
                )
            )
            action = "created"
        else:
            user.password_hash = pwd_hash
            user.role = role
            user.is_active = True
            action = "updated"
        await session.commit()
    await dispose_engine()
    print(f"Admin user {action}: {username} (role={role})")
    print("Store WEB_ADMIN_PASSWORD_HASH only if using bootstrap; password is hashed in DB.")
    print(f"Hash (optional env): {pwd_hash}")
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(description="Create TG-forwarder web admin user")
    parser.add_argument("--username", default=os.environ.get("WEB_ADMIN_USERNAME", "admin"))
    parser.add_argument("--role", default=Role.SUPER_ADMIN.value, choices=[r.value for r in Role])
    parser.add_argument("--password", default="", help="Prefer prompt; avoid shell history")
    args = parser.parse_args()
    password = args.password or getpass.getpass("Admin password: ")
    if len(password) < 8:
        print("Password must be at least 8 characters", file=sys.stderr)
        raise SystemExit(1)
    clear_settings_cache()
    raise SystemExit(asyncio.run(_run(args.username, password, args.role)))


if __name__ == "__main__":
    main()
