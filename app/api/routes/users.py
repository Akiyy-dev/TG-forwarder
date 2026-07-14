"""User management routes (super_admin)."""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query
from pydantic import Field
from sqlalchemy import func, select

from app.api.dependencies import SuperAdminUser, get_ctx
from app.api.errors import AppError
from app.api.pagination import PageParams, build_page
from app.api.schemas import APIModel, Envelope, UserOut
from app.auth.roles import Role
from app.auth.service import AuthError, AuthService
from app.context import AppContext
from app.database.models import User

router = APIRouter(prefix="/users", tags=["users"])


class CreateUserRequest(APIModel):
    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=8, max_length=256)
    role: Role = Role.VIEWER


@router.get("", response_model=Envelope[dict[str, Any]])
async def list_users(
    _admin: SuperAdminUser,
    ctx: Annotated[AppContext, Depends(get_ctx)],
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
) -> Envelope[dict[str, Any]]:
    params = PageParams(page=page, page_size=page_size)
    async with ctx.session_factory() as session:
        total = int((await session.execute(select(func.count()).select_from(User))).scalar_one())
        result = await session.execute(
            select(User).order_by(User.id.asc()).offset(params.offset).limit(params.page_size)
        )
        users = list(result.scalars().all())
    items = [UserOut.model_validate(u).model_dump(mode="json") for u in users]
    return Envelope(data=build_page(items=items, total=total, params=params))


@router.post("", response_model=Envelope[UserOut])
async def create_user(
    body: CreateUserRequest,
    _admin: SuperAdminUser,
    ctx: Annotated[AppContext, Depends(get_ctx)],
) -> Envelope[UserOut]:
    auth: AuthService = ctx.auth_service
    try:
        user = await auth.create_user(
            username=body.username,
            password=body.password,
            role=body.role,
        )
    except AuthError as exc:
        raise AppError("user_create_failed", exc.message, status_code=400) from exc
    return Envelope(data=UserOut.model_validate(user))
