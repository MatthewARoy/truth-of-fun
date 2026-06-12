"""Add source_health table for cross-process worker health reporting.

Revision ID: 202606120001
Revises: 67ae74b20ec1
Create Date: 2026-06-12
"""

from typing import Union

import sqlalchemy as sa
from alembic import op

revision: str = "202606120001"
down_revision: Union[str, None] = "67ae74b20ec1"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "source_health",
        sa.Column("source_name", sa.String(length=128), primary_key=True),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("last_event_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("consecutive_zeros", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("last_run_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_table("source_health")
