"""review tasks, actions, revisions

Revision ID: 0003_review_tasks
Revises: 0002_web_auth
Create Date: 2026-07-14

"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0003_review_tasks"
down_revision: Union[str, None] = "0002_web_auth"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "review_tasks",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("processed_message_id", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("source_chat_id", sa.BigInteger(), nullable=False),
        sa.Column("source_message_id", sa.BigInteger(), nullable=False),
        sa.Column("target_chat_id", sa.BigInteger(), nullable=True),
        sa.Column("original_text", sa.Text(), nullable=False),
        sa.Column("processed_text", sa.Text(), nullable=False),
        sa.Column("final_text", sa.Text(), nullable=False),
        sa.Column("media_type", sa.String(length=32), nullable=False),
        sa.Column("media_count", sa.Integer(), nullable=False),
        sa.Column("matched_rules", sa.JSON(), nullable=True),
        sa.Column("detected_keywords", sa.JSON(), nullable=True),
        sa.Column("decision_reason", sa.String(length=512), nullable=True),
        sa.Column("assigned_user_id", sa.Integer(), nullable=True),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("published_revision", sa.Integer(), nullable=True),
        sa.Column("media_snapshot", sa.JSON(), nullable=True),
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
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("rejected_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("publishing_started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(["assigned_user_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["processed_message_id"], ["processed_messages.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("processed_message_id"),
    )
    op.create_index("ix_review_tasks_processed_message_id", "review_tasks", ["processed_message_id"])
    op.create_index("ix_review_tasks_status", "review_tasks", ["status"])
    op.create_index(
        "ix_review_tasks_source", "review_tasks", ["source_chat_id", "source_message_id"]
    )

    op.create_table(
        "review_actions",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("review_task_id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=True),
        sa.Column("action", sa.String(length=64), nullable=False),
        sa.Column("old_status", sa.String(length=32), nullable=True),
        sa.Column("new_status", sa.String(length=32), nullable=True),
        sa.Column("detail", sa.JSON(), nullable=True),
        sa.Column("client_ip", sa.String(length=64), nullable=True),
        sa.Column("user_agent", sa.String(length=512), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["review_task_id"], ["review_tasks.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_review_actions_review_task_id", "review_actions", ["review_task_id"])

    op.create_table(
        "content_revisions",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("review_task_id", sa.Integer(), nullable=False),
        sa.Column("revision_number", sa.Integer(), nullable=False),
        sa.Column("source", sa.String(length=32), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("created_by", sa.Integer(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"]),
        sa.ForeignKeyConstraint(["review_task_id"], ["review_tasks.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("review_task_id", "revision_number", name="uq_review_revision"),
    )
    op.create_index("ix_content_revisions_review_task_id", "content_revisions", ["review_task_id"])


def downgrade() -> None:
    op.drop_index("ix_content_revisions_review_task_id", table_name="content_revisions")
    op.drop_table("content_revisions")
    op.drop_index("ix_review_actions_review_task_id", table_name="review_actions")
    op.drop_table("review_actions")
    op.drop_index("ix_review_tasks_source", table_name="review_tasks")
    op.drop_index("ix_review_tasks_status", table_name="review_tasks")
    op.drop_index("ix_review_tasks_processed_message_id", table_name="review_tasks")
    op.drop_table("review_tasks")
