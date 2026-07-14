"""FastAPI dependencies."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Annotated, cast

from fastapi import Cookie, Depends, Request

from app.api.errors import AppError
from app.auth.roles import Role, role_at_least
from app.auth.service import AuthError, AuthService
from app.auth.tokens import ACCESS_COOKIE
from app.context import AppContext
from app.database.models import User


def get_ctx(request: Request) -> AppContext:
    ctx = getattr(request.app.state, "ctx", None)
    if ctx is None:
        raise AppError("app_not_ready", "Application context missing", status_code=503)
    return cast(AppContext, ctx)


def get_auth_service(ctx: Annotated[AppContext, Depends(get_ctx)]) -> AuthService:
    return ctx.auth_service


async def get_current_user(
    request: Request,
    ctx: Annotated[AppContext, Depends(get_ctx)],
    access_token: Annotated[str | None, Cookie(alias=ACCESS_COOKIE)] = None,
) -> User:
    token = access_token
    if not token:
        auth = request.headers.get("Authorization")
        if auth and auth.lower().startswith("bearer "):
            token = auth[7:].strip()
    if not token:
        raise AppError("unauthorized", "Not authenticated", status_code=401)
    try:
        return await ctx.auth_service.get_user_from_access(token)
    except AuthError as exc:
        raise AppError("unauthorized", str(exc), status_code=401) from exc


def require_roles(*roles: Role) -> Callable[..., Awaitable[User]]:
    minimum = max(roles, key=lambda r: {"viewer": 1, "reviewer": 2, "super_admin": 3}[r.value])

    async def _dep(user: Annotated[User, Depends(get_current_user)]) -> User:
        if not role_at_least(user.role, minimum):
            raise AppError("forbidden", "Insufficient permissions", status_code=403)
        return user

    return _dep


CurrentUser = Annotated[User, Depends(get_current_user)]
SuperAdminUser = Annotated[User, Depends(require_roles(Role.SUPER_ADMIN))]
ReviewerUser = Annotated[User, Depends(require_roles(Role.REVIEWER))]
ViewerUser = Annotated[User, Depends(require_roles(Role.VIEWER))]
