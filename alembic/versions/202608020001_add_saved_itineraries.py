"""Add saved_itineraries so a concierge plan can be shared as a link.

Revision ID: 202608020001
Revises: 202606130001
Create Date: 2026-08-02
"""

from typing import Union

import sqlalchemy as sa
from alembic import op

revision: str = "202608020001"
down_revision: Union[str, None] = "202606130001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "saved_itineraries",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("share_token", sa.String(length=64), nullable=False, unique=True, index=True),
        sa.Column(
            "user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=True, index=True
        ),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("query", sa.String(), nullable=False),
        sa.Column("intent", sa.String(length=100), nullable=False),
        sa.Column("timeframe", sa.String(length=100), nullable=False),
        sa.Column("geography", sa.String(length=255), nullable=True),
        # Not a foreign key: the snapshot has to survive the anchor event being
        # merged away by the dedupe pipeline.
        sa.Column("anchor_event_id", sa.Integer(), nullable=True),
        sa.Column("stops", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )


def downgrade() -> None:
    op.drop_table("saved_itineraries")
