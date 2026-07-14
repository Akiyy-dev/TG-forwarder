"""Authentication and user management service."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from jose import JWTError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.auth.passwords import hash_password, verify_password
from app.auth.roles import Role
from app.auth.tokens import (
    create_access_token,
    create_refresh_token_value,
    decode_access_token,
    hash_token,
)
from app.config import Settings
from app.database.models import RefreshToken, User
from app.logging import get_logger

logger = get_logger(__name__)

GENERIC_AUTH_ERROR = "Invalid username or password"


class AuthError(Exception):
    def __init__(self, message: str = GENERIC_AUTH_ERROR) -> None:
        self.message = message
        super().__init__(message)


class AuthService:
    def __init__(
        self,
        settings: Settings,
        session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        self.settings = settings
        self.session_factory = session_factory

    async def ensure_bootstrap_admin(self) -> None:
        """Create initial admin from env hash if no users exist."""
        async with self.session_factory() as session:
            result = await session.execute(select(User).limit(1))
            if result.scalar_one_or_none() is not None:
                return
            pwd_hash = self.settings.web_admin_password_hash.strip()
            if not pwd_hash:
                logger.warning("bootstrap_admin_skipped_no_password_hash")
                return
            user = User(
                username=self.settings.web_admin_username.strip() or "admin",
                password_hash=pwd_hash,
                role=Role.SUPER_ADMIN.value,
                is_active=True,
            )
            session.add(user)
            await session.commit()
            logger.info("bootstrap_admin_created", username=user.username)

    async def create_user(
        self,
        *,
        username: str,
        password: str,
        role: Role = Role.VIEWER,
    ) -> User:
        async with self.session_factory() as session:
            existing = await session.execute(select(User).where(User.username == username))
            if existing.scalar_one_or_none() is not None:
                msg = "username already exists"
                raise AuthError(msg)
            user = User(
                username=username,
                password_hash=hash_password(password),
                role=role.value,
                is_active=True,
            )
            session.add(user)
            await session.commit()
            await session.refresh(user)
            return user

    async def authenticate(self, username: str, password: str) -> User:
        async with self.session_factory() as session:
            result = await session.execute(select(User).where(User.username == username))
            user = result.scalar_one_or_none()
            if user is None or not user.is_active:
                raise AuthError()
            if not verify_password(password, user.password_hash):
                raise AuthError()
            user.last_login_at = datetime.now(UTC)
            await session.commit()
            await session.refresh(user)
            return user

    async def issue_tokens(self, user: User) -> tuple[str, str, datetime]:
        access = create_access_token(
            secret_key=self.settings.web_secret_key,
            subject=str(user.id),
            role=user.role,
            expires_minutes=self.settings.web_access_token_expire_minutes,
            extra={"username": user.username},
        )
        refresh = create_refresh_token_value()
        expires = datetime.now(UTC) + timedelta(days=self.settings.web_refresh_token_expire_days)
        async with self.session_factory() as session:
            session.add(
                RefreshToken(
                    user_id=user.id,
                    token_hash=hash_token(refresh),
                    expires_at=expires,
                )
            )
            await session.commit()
        return access, refresh, expires

    async def refresh(self, refresh_token: str) -> tuple[str, str, datetime, User]:
        token_digest = hash_token(refresh_token)
        async with self.session_factory() as session:
            result = await session.execute(
                select(RefreshToken).where(RefreshToken.token_hash == token_digest)
            )
            row = result.scalar_one_or_none()
            if row is None or row.revoked_at is not None:
                raise AuthError()
            expires_at = row.expires_at
            if expires_at.tzinfo is None:
                expires_at = expires_at.replace(tzinfo=UTC)
            if expires_at < datetime.now(UTC):
                raise AuthError()
            user = await session.get(User, row.user_id)
            if user is None or not user.is_active:
                raise AuthError()
            row.revoked_at = datetime.now(UTC)
            user_id = user.id
            await session.commit()

        async with self.session_factory() as session:
            user = await session.get(User, user_id)
            assert user is not None
            access, new_refresh, new_exp = await self.issue_tokens(user)
            return access, new_refresh, new_exp, user

    async def revoke_refresh(self, refresh_token: str | None) -> None:
        if not refresh_token:
            return
        digest = hash_token(refresh_token)
        async with self.session_factory() as session:
            result = await session.execute(
                select(RefreshToken).where(RefreshToken.token_hash == digest)
            )
            row = result.scalar_one_or_none()
            if row is not None and row.revoked_at is None:
                row.revoked_at = datetime.now(UTC)
                await session.commit()

    async def get_user_from_access(self, token: str) -> User:
        try:
            payload = decode_access_token(token, self.settings.web_secret_key)
        except JWTError as exc:
            raise AuthError("Not authenticated") from exc
        user_id = int(payload["sub"])
        async with self.session_factory() as session:
            user = await session.get(User, user_id)
            if user is None or not user.is_active:
                raise AuthError("Not authenticated")
            # Detach fields we need
            session.expunge(user)
            return user

    async def change_password(
        self,
        user_id: int,
        *,
        current_password: str,
        new_password: str,
    ) -> None:
        if len(new_password) < 8:
            msg = "password must be at least 8 characters"
            raise AuthError(msg)
        async with self.session_factory() as session:
            user = await session.get(User, user_id)
            if user is None:
                raise AuthError("Not authenticated")
            if not verify_password(current_password, user.password_hash):
                raise AuthError("Invalid current password")
            user.password_hash = hash_password(new_password)
            # Revoke all refresh tokens
            result = await session.execute(
                select(RefreshToken).where(
                    RefreshToken.user_id == user_id,
                    RefreshToken.revoked_at.is_(None),
                )
            )
            for row in result.scalars().all():
                row.revoked_at = datetime.now(UTC)
            await session.commit()
