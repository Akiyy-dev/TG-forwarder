"""channel access status, source-target links, review target_chat_ids

Revision ID: 0006_channel_links_access
Revises: 0005_channel_publish_modes
Create Date: 2026-07-16

"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0006_channel_links_access"
down_revision: Union[str, None] = "0005_channel_publish_modes"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "source_channels",
        sa.Column("access_status", sa.String(length=32), nullable=False, server_default="unknown"),
    )
    op.add_column(
        "target_channels",
        sa.Column("access_status", sa.String(length=32), nullable=False, server_default="unknown"),
    )
    op.add_column(
        "review_tasks",
        sa.Column("target_chat_ids", sa.JSON(), nullable=True),
    )

    op.create_table(
        "source_target_links",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("source_id", sa.Integer(), nullable=False),
        sa.Column("target_id", sa.Integer(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["source_id"], ["source_channels.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["target_id"], ["target_channels.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("source_id", "target_id", name="uq_source_target_link"),
    )
    op.create_index("ix_source_target_links_source_id", "source_target_links", ["source_id"])
    op.create_index("ix_source_target_links_target_id", "source_target_links", ["target_id"])

    # Backfill links from legacy source_channels.target_channel_id (Telegram chat id).
    conn = op.get_bind()
    rows = conn.execute(
        sa.text(
            "SELECT id, target_channel_id FROM source_channels "
            "WHERE target_channel_id IS NOT NULL"
        )
    ).fetchall()
    for source_id, target_chat_id in rows:
        target = conn.execute(
            sa.text("SELECT id FROM target_channels WHERE chat_id = :cid"),
            {"cid": target_chat_id},
        ).fetchone()
        if target is None:
            continue
        conn.execute(
            sa.text(
                "INSERT OR IGNORE INTO source_target_links (source_id, target_id) "
                "VALUES (:sid, :tid)"
            ),
            {"sid": source_id, "tid": target[0]},
        )


def downgrade() -> None:
    op.drop_index("ix_source_target_links_target_id", table_name="source_target_links")
    op.drop_index("ix_source_target_links_source_id", table_name="source_target_links")
    op.drop_table("source_target_links")
    op.drop_column("review_tasks", "target_chat_ids")
    op.drop_column("target_channels", "access_status")
    op.drop_column("source_channels", "access_status")
