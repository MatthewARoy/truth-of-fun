"""Add organizer, attendee count, location confidence, and is_free to events.

Revision ID: 202606120002
Revises: 202606120001
Create Date: 2026-06-12
"""

from typing import Union

import sqlalchemy as sa
from alembic import op

revision: str = "202606120002"
down_revision: Union[str, None] = "202606120001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("events", sa.Column("organizer_name", sa.String(length=255), nullable=True))
    op.add_column(
        "events",
        sa.Column("attendee_count", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column(
        "events",
        sa.Column("location_confidence", sa.Float(), nullable=False, server_default="1.0"),
    )
    op.add_column(
        "events",
        sa.Column("is_free", sa.Boolean(), nullable=False, server_default="false"),
    )


def downgrade() -> None:
    op.drop_column("events", "is_free")
    op.drop_column("events", "location_confidence")
    op.drop_column("events", "attendee_count")
    op.drop_column("events", "organizer_name")
