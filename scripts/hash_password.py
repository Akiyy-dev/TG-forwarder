"""Generate an Argon2 hash for WEB_ADMIN_PASSWORD_HASH without exposing argv."""

from __future__ import annotations

from getpass import getpass

from app.auth.passwords import hash_password


def main() -> None:
    password = getpass("Web admin password: ")
    confirm = getpass("Confirm password: ")
    if len(password) < 8:
        raise SystemExit("Password must contain at least 8 characters")
    if password != confirm:
        raise SystemExit("Passwords do not match")
    print("WEB_ADMIN_PASSWORD_HASH='" + hash_password(password) + "'")


if __name__ == "__main__":
    main()
