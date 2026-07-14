"""Shared API response helpers and auth schemas."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Generic, TypeVar

from pydantic import BaseModel, Field

T = TypeVar("T")


class APIModel(BaseModel):
    model_config = {"from_attributes": True}


class Envelope(APIModel, Generic[T]):
    ok: bool = True
    data: T
    meta: dict[str, Any] = Field(default_factory=dict)


class LoginRequest(APIModel):
    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=1, max_length=256)


class ChangePasswordRequest(APIModel):
    current_password: str = Field(min_length=1, max_length=256)
    new_password: str = Field(min_length=8, max_length=256)


class UserOut(APIModel):
    id: int
    username: str
    role: str
    is_active: bool
    last_login_at: datetime | None = None


class LoginData(APIModel):
    user: UserOut
    access_expires_minutes: int
