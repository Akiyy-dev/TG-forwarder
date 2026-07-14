"""channel publish modes and target channels

Revision ID: 0005_channel_publish_modes
Revises: 0004_keyword_rules
Create Date: 2026-07-15

"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0005_channel_publish_modes"
down_revision: Union[str, None] = "0004_keyword_rules"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "source_channels",
        sa.Column("publish_mode", sa.String(length=32), nullable=False, server_default="review"),
    )
    op.create_index("ix_source_channels_publish_mode", "source_channels", ["publish_mode"])

    op.create_table(
        "target_channels",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("chat_id", sa.BigInteger(), nullable=False),
        sa.Column("username", sa.String(length=255), nullable=True),
        sa.Column("title", sa.String(length=512), nullable=True),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("default_footer", sa.Text(), nullable=True),
        sa.Column("permission_status", sa.String(length=32), nullable=False),
        sa.Column("permission_detail", sa.JSON(), nullable=True),
        sa.Column("last_permission_check_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("chat_id"),
    )
    op.create_index("ix_target_channels_chat_id", "target_channels", ["chat_id"])


def downgrade() -> None:
    op.drop_index("ix_target_channels_chat_id", table_name="target_channels")
    op.drop_table("target_channels")
    op.drop_index("ix_source_channels_publish_mode", table_name="source_channels")
    op.drop_column("source_channels", "publish_mode")
