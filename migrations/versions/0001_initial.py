"""initial schema

Revision ID: 0001_initial
Revises:
Create Date: 2026-07-14

"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0001_initial"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "source_channels",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("chat_id", sa.BigInteger(), nullable=False),
        sa.Column("username", sa.String(length=255), nullable=True),
        sa.Column("title", sa.String(length=512), nullable=True),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("target_channel_id", sa.BigInteger(), nullable=True),
        sa.Column("processing_profile", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("(CURRENT_TIMESTAMP)"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("(CURRENT_TIMESTAMP)"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("chat_id"),
    )
    op.create_index("ix_source_channels_chat_id", "source_channels", ["chat_id"])

    op.create_table(
        "processed_messages",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("source_chat_id", sa.BigInteger(), nullable=False),
        sa.Column("source_message_id", sa.BigInteger(), nullable=False),
        sa.Column("grouped_id", sa.BigInteger(), nullable=True),
        sa.Column("content_hash", sa.String(length=64), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("skip_reason", sa.String(length=512), nullable=True),
        sa.Column("processing_result", sa.JSON(), nullable=True),
        sa.Column("target_chat_id", sa.BigInteger(), nullable=True),
        sa.Column("target_message_ids", sa.JSON(), nullable=True),
        sa.Column("retry_count", sa.Integer(), nullable=False),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("received_at", sa.DateTime(timezone=True), server_default=sa.text("(CURRENT_TIMESTAMP)"), nullable=False),
        sa.Column("processed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("(CURRENT_TIMESTAMP)"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("(CURRENT_TIMESTAMP)"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("source_chat_id", "source_message_id", name="uq_source_message"),
    )
    op.create_index("ix_processed_content_hash", "processed_messages", ["content_hash"])
    op.create_index("ix_processed_status", "processed_messages", ["status"])
    op.create_index("ix_processed_grouped", "processed_messages", ["source_chat_id", "grouped_id"])

    op.create_table(
        "processing_logs",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("message_record_id", sa.Integer(), nullable=False),
        sa.Column("processor_name", sa.String(length=128), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("detail", sa.JSON(), nullable=True),
        sa.Column("duration_ms", sa.Float(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("(CURRENT_TIMESTAMP)"), nullable=False),
        sa.ForeignKeyConstraint(["message_record_id"], ["processed_messages.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_processing_logs_message_record_id", "processing_logs", ["message_record_id"])

    op.create_table(
        "app_settings",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("key", sa.String(length=128), nullable=False),
        sa.Column("value", sa.JSON(), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("(CURRENT_TIMESTAMP)"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("key"),
    )


def downgrade() -> None:
    op.drop_table("app_settings")
    op.drop_index("ix_processing_logs_message_record_id", table_name="processing_logs")
    op.drop_table("processing_logs")
    op.drop_index("ix_processed_grouped", table_name="processed_messages")
    op.drop_index("ix_processed_status", table_name="processed_messages")
    op.drop_index("ix_processed_content_hash", table_name="processed_messages")
    op.drop_table("processed_messages")
    op.drop_index("ix_source_channels_chat_id", table_name="source_channels")
    op.drop_table("source_channels")
