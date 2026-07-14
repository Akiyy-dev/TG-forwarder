"""Authentication routes."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Cookie, Depends, Request, Response

from app.api.dependencies import CurrentUser, get_auth_service, get_ctx
from app.api.errors import AppError
from app.api.schemas import (
    ChangePasswordRequest,
    Envelope,
    LoginData,
    LoginRequest,
    UserOut,
)
from app.auth.service import AuthError, AuthService
from app.auth.tokens import ACCESS_COOKIE, REFRESH_COOKIE
from app.context import AppContext

router = APIRouter(prefix="/auth", tags=["auth"])


def _set_auth_cookies(
    response: Response,
    ctx: AppContext,
    *,
    access: str,
    refresh: str,
) -> None:
    settings = ctx.settings
    common = {
        "httponly": True,
        "samesite": "lax",
        "secure": settings.web_secure_cookies,
        "path": "/",
    }
    response.set_cookie(
        ACCESS_COOKIE,
        access,
        max_age=settings.web_access_token_expire_minutes * 60,
        **common,  # type: ignore[arg-type]
    )
    response.set_cookie(
        REFRESH_COOKIE,
        refresh,
        max_age=settings.web_refresh_token_expire_days * 24 * 3600,
        **common,  # type: ignore[arg-type]
    )


def _clear_auth_cookies(response: Response, ctx: AppContext) -> None:
    response.delete_cookie(ACCESS_COOKIE, path="/")
    response.delete_cookie(REFRESH_COOKIE, path="/")


@router.post("/login", response_model=Envelope[LoginData])
async def login(
    body: LoginRequest,
    request: Request,
    response: Response,
    ctx: Annotated[AppContext, Depends(get_ctx)],
    auth: Annotated[AuthService, Depends(get_auth_service)],
) -> Envelope[LoginData]:
    client = request.client.host if request.client else "unknown"
    assert ctx.login_limiter is not None
    if not ctx.login_limiter.allow(f"login:{client}"):
        raise AppError("rate_limited", "Too many login attempts", status_code=429)
    try:
        user = await auth.authenticate(body.username, body.password)
        access, refresh, _exp = await auth.issue_tokens(user)
    except AuthError as exc:
        raise AppError("auth_failed", exc.message, status_code=401) from exc
    _set_auth_cookies(response, ctx, access=access, refresh=refresh)
    return Envelope(
        data=LoginData(
            user=UserOut.model_validate(user),
            access_expires_minutes=ctx.settings.web_access_token_expire_minutes,
        )
    )


@router.post("/refresh", response_model=Envelope[LoginData])
async def refresh(
    response: Response,
    ctx: Annotated[AppContext, Depends(get_ctx)],
    auth: Annotated[AuthService, Depends(get_auth_service)],
    refresh_token: Annotated[str | None, Cookie(alias=REFRESH_COOKIE)] = None,
) -> Envelope[LoginData]:
    if not refresh_token:
        raise AppError("unauthorized", "Not authenticated", status_code=401)
    try:
        access, new_refresh, _exp, user = await auth.refresh(refresh_token)
    except AuthError as exc:
        raise AppError("unauthorized", exc.message, status_code=401) from exc
    _set_auth_cookies(response, ctx, access=access, refresh=new_refresh)
    return Envelope(
        data=LoginData(
            user=UserOut.model_validate(user),
            access_expires_minutes=ctx.settings.web_access_token_expire_minutes,
        )
    )


@router.post("/logout", response_model=Envelope[dict[str, bool]])
async def logout(
    response: Response,
    ctx: Annotated[AppContext, Depends(get_ctx)],
    auth: Annotated[AuthService, Depends(get_auth_service)],
    refresh_token: Annotated[str | None, Cookie(alias=REFRESH_COOKIE)] = None,
) -> Envelope[dict[str, bool]]:
    await auth.revoke_refresh(refresh_token)
    _clear_auth_cookies(response, ctx)
    return Envelope(data={"logged_out": True})


@router.get("/me", response_model=Envelope[UserOut])
async def me(user: CurrentUser) -> Envelope[UserOut]:
    return Envelope(data=UserOut.model_validate(user))


@router.post("/change-password", response_model=Envelope[dict[str, bool]])
async def change_password(
    body: ChangePasswordRequest,
    user: CurrentUser,
    auth: Annotated[AuthService, Depends(get_auth_service)],
) -> Envelope[dict[str, bool]]:
    try:
        await auth.change_password(
            user.id,
            current_password=body.current_password,
            new_password=body.new_password,
        )
    except AuthError as exc:
        raise AppError("password_change_failed", exc.message, status_code=400) from exc
    return Envelope(data={"changed": True})
