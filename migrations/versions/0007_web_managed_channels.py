"""remove unregistered legacy target assignments

Revision ID: 0007_web_managed_channels
Revises: 0006_channel_links_access
Create Date: 2026-07-17

"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0007_web_managed_channels"
down_revision: str | None = "0006_channel_links_access"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Clear target ids that are not represented by a Web-managed link."""

    op.execute(
        sa.text(
            """
            UPDATE source_channels
            SET target_channel_id = NULL
            WHERE target_channel_id IS NOT NULL
              AND NOT EXISTS (
                  SELECT 1
                  FROM source_target_links AS link
                  JOIN target_channels AS target ON target.id = link.target_id
                  WHERE link.source_id = source_channels.id
                    AND target.chat_id = source_channels.target_channel_id
              )
            """
        )
    )


def downgrade() -> None:
    # Removed environment assignments cannot be reconstructed safely.
    pass
