"""keyword rules and execution logs

Revision ID: 0004_keyword_rules
Revises: 0003_review_tasks
Create Date: 2026-07-14

"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0004_keyword_rules"
down_revision: Union[str, None] = "0003_review_tasks"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "rule_groups",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("name", sa.String(length=128), nullable=False),
        sa.Column("description", sa.String(length=512), nullable=True),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("priority", sa.Integer(), nullable=False),
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
        sa.UniqueConstraint("name"),
    )
    op.create_table(
        "keyword_rules",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("name", sa.String(length=128), nullable=False),
        sa.Column("description", sa.String(length=512), nullable=True),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("priority", sa.Integer(), nullable=False),
        sa.Column("rule_type", sa.String(length=32), nullable=False),
        sa.Column("match_type", sa.String(length=32), nullable=False),
        sa.Column("pattern", sa.Text(), nullable=False),
        sa.Column("replacement", sa.Text(), nullable=True),
        sa.Column("case_sensitive", sa.Boolean(), nullable=False),
        sa.Column("whole_word", sa.Boolean(), nullable=False),
        sa.Column("use_regex", sa.Boolean(), nullable=False),
        sa.Column("source_channel_ids", sa.JSON(), nullable=True),
        sa.Column("target_channel_ids", sa.JSON(), nullable=True),
        sa.Column("message_types", sa.JSON(), nullable=True),
        sa.Column("action", sa.String(length=32), nullable=False),
        sa.Column("stop_processing", sa.Boolean(), nullable=False),
        sa.Column("group_id", sa.Integer(), nullable=True),
        sa.Column("hit_count", sa.Integer(), nullable=False),
        sa.Column("last_hit_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_by", sa.Integer(), nullable=True),
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
        sa.ForeignKeyConstraint(["created_by"], ["users.id"]),
        sa.ForeignKeyConstraint(["group_id"], ["rule_groups.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_keyword_rules_priority", "keyword_rules", ["priority"])

    op.create_table(
        "rule_execution_logs",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("processed_message_id", sa.Integer(), nullable=True),
        sa.Column("review_task_id", sa.Integer(), nullable=True),
        sa.Column("rule_id", sa.Integer(), nullable=True),
        sa.Column("rule_name", sa.String(length=128), nullable=False),
        sa.Column("action", sa.String(length=32), nullable=False),
        sa.Column("matched_text", sa.String(length=512), nullable=True),
        sa.Column("replacement_text", sa.String(length=512), nullable=True),
        sa.Column("match_start", sa.Integer(), nullable=True),
        sa.Column("match_end", sa.Integer(), nullable=True),
        sa.Column("before_excerpt", sa.String(length=512), nullable=True),
        sa.Column("after_excerpt", sa.String(length=512), nullable=True),
        sa.Column("duration_ms", sa.Float(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["processed_message_id"], ["processed_messages.id"], ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(["review_task_id"], ["review_tasks.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["rule_id"], ["keyword_rules.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_rule_execution_logs_processed_message_id",
        "rule_execution_logs",
        ["processed_message_id"],
    )
    op.create_index(
        "ix_rule_execution_logs_review_task_id",
        "rule_execution_logs",
        ["review_task_id"],
    )
    op.create_index("ix_rule_execution_logs_rule_id", "rule_execution_logs", ["rule_id"])


def downgrade() -> None:
    op.drop_index("ix_rule_execution_logs_rule_id", table_name="rule_execution_logs")
    op.drop_index("ix_rule_execution_logs_review_task_id", table_name="rule_execution_logs")
    op.drop_index(
        "ix_rule_execution_logs_processed_message_id", table_name="rule_execution_logs"
    )
    op.drop_table("rule_execution_logs")
    op.drop_index("ix_keyword_rules_priority", table_name="keyword_rules")
    op.drop_table("keyword_rules")
    op.drop_table("rule_groups")
