"""Web user roles."""

from __future__ import annotations

from enum import StrEnum


class Role(StrEnum):
    SUPER_ADMIN = "super_admin"
    REVIEWER = "reviewer"
    VIEWER = "viewer"


ROLE_RANK: dict[Role, int] = {
    Role.VIEWER: 1,
    Role.REVIEWER: 2,
    Role.SUPER_ADMIN: 3,
}


def role_at_least(user_role: str, required: Role) -> bool:
    try:
        current = Role(user_role)
    except ValueError:
        return False
    return ROLE_RANK[current] >= ROLE_RANK[required]
