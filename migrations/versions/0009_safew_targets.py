"""add SafeW Bot API targets

Revision ID: 0009_safew_targets
Revises: 0008_api_destinations
Create Date: 2026-07-20

"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0009_safew_targets"
down_revision: str | None = "0008_api_destinations"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


_NAMING_CONVENTION = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


def _legacy_chat_unique_name() -> str | None:
    constraints = sa.inspect(op.get_bind()).get_unique_constraints("target_channels")
    for constraint in constraints:
        if constraint.get("column_names") == ["chat_id"]:
            name = constraint.get("name")
            return str(name) if name else None
    return None


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "sqlite":
        # SQLite's original one-column UNIQUE constraint is unnamed, so use a
        # naming convention while Alembic recreates the table.
        with op.batch_alter_table(
            "target_channels",
            recreate="always",
            naming_convention=_NAMING_CONVENTION,
        ) as batch_op:
            batch_op.add_column(
                sa.Column(
                    "target_backend",
                    sa.String(length=32),
                    nullable=False,
                    server_default="telegram",
                )
            )
            batch_op.drop_constraint("uq_target_channels_chat_id", type_="unique")
            batch_op.create_unique_constraint(
                "uq_target_channel_backend_chat",
                ["target_backend", "chat_id"],
            )
    else:
        legacy_name = _legacy_chat_unique_name()
        op.add_column(
            "target_channels",
            sa.Column(
                "target_backend",
                sa.String(length=32),
                nullable=False,
                server_default="telegram",
            ),
        )
        if legacy_name:
            op.drop_constraint(legacy_name, "target_channels", type_="unique")
        op.create_unique_constraint(
            "uq_target_channel_backend_chat",
            "target_channels",
            ["target_backend", "chat_id"],
        )

    op.create_index(
        "ix_target_channels_target_backend",
        "target_channels",
        ["target_backend"],
    )
    op.add_column(
        "review_tasks",
        sa.Column("target_destination_ids", sa.JSON(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("review_tasks", "target_destination_ids")
    op.drop_index("ix_target_channels_target_backend", table_name="target_channels")
    bind = op.get_bind()
    if bind.dialect.name == "sqlite":
        with op.batch_alter_table(
            "target_channels",
            recreate="always",
            naming_convention=_NAMING_CONVENTION,
        ) as batch_op:
            batch_op.drop_constraint("uq_target_channel_backend_chat", type_="unique")
            batch_op.create_unique_constraint("uq_target_channels_chat_id", ["chat_id"])
            batch_op.drop_column("target_backend")
    else:
        op.drop_constraint(
            "uq_target_channel_backend_chat",
            "target_channels",
            type_="unique",
        )
        op.create_unique_constraint(None, "target_channels", ["chat_id"])
        op.drop_column("target_channels", "target_backend")
