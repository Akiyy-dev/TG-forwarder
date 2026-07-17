"""add public API destinations and delivery queue

Revision ID: 0008_api_destinations
Revises: 0007_web_managed_channels
Create Date: 2026-07-17

"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0008_api_destinations"
down_revision: str | None = "0007_web_managed_channels"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "api_endpoints",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("name", sa.String(length=128), nullable=False),
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column("token_prefix", sa.String(length=16), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_access_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("token_hash"),
    )
    op.create_index("ix_api_endpoints_token_hash", "api_endpoints", ["token_hash"])

    op.create_table(
        "source_api_endpoint_links",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("source_id", sa.Integer(), nullable=False),
        sa.Column("api_endpoint_id", sa.Integer(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(["api_endpoint_id"], ["api_endpoints.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["source_id"], ["source_channels.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("source_id", "api_endpoint_id", name="uq_source_api_endpoint_link"),
    )
    op.create_index(
        "ix_source_api_endpoint_links_source_id", "source_api_endpoint_links", ["source_id"]
    )
    op.create_index(
        "ix_source_api_endpoint_links_api_endpoint_id",
        "source_api_endpoint_links",
        ["api_endpoint_id"],
    )

    op.add_column("review_tasks", sa.Column("target_api_endpoint_ids", sa.JSON(), nullable=True))

    op.create_table(
        "api_deliveries",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("api_endpoint_id", sa.Integer(), nullable=False),
        sa.Column("processed_message_id", sa.Integer(), nullable=False),
        sa.Column("review_task_id", sa.Integer(), nullable=True),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(["api_endpoint_id"], ["api_endpoints.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["processed_message_id"], ["processed_messages.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["review_task_id"], ["review_tasks.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "api_endpoint_id",
            "processed_message_id",
            name="uq_api_delivery_endpoint_message",
        ),
    )
    op.create_index("ix_api_deliveries_api_endpoint_id", "api_deliveries", ["api_endpoint_id"])
    op.create_index(
        "ix_api_deliveries_processed_message_id", "api_deliveries", ["processed_message_id"]
    )
    op.create_index("ix_api_deliveries_review_task_id", "api_deliveries", ["review_task_id"])
    op.create_index(
        "ix_api_deliveries_endpoint_cursor", "api_deliveries", ["api_endpoint_id", "id"]
    )


def downgrade() -> None:
    op.drop_index("ix_api_deliveries_endpoint_cursor", table_name="api_deliveries")
    op.drop_index("ix_api_deliveries_review_task_id", table_name="api_deliveries")
    op.drop_index("ix_api_deliveries_processed_message_id", table_name="api_deliveries")
    op.drop_index("ix_api_deliveries_api_endpoint_id", table_name="api_deliveries")
    op.drop_table("api_deliveries")
    op.drop_column("review_tasks", "target_api_endpoint_ids")
    op.drop_index(
        "ix_source_api_endpoint_links_api_endpoint_id",
        table_name="source_api_endpoint_links",
    )
    op.drop_index("ix_source_api_endpoint_links_source_id", table_name="source_api_endpoint_links")
    op.drop_table("source_api_endpoint_links")
    op.drop_index("ix_api_endpoints_token_hash", table_name="api_endpoints")
    op.drop_table("api_endpoints")
