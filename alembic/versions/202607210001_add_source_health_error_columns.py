"""Add error/success tracking columns to source_health.

A source that raises during fetch and a source that legitimately returns no
events both recorded last_event_count=0, so GET /health/sources could not tell
"the scraper broke" from "nothing was on". These columns persist the failure
text and the last known-good run so breakage is visible without reading logs.

Revision ID: 202607210001
Revises: 202606130001
Create Date: 2026-07-21
"""

from typing import Union

import sqlalchemy as sa
from alembic import op

revision: str = "202607210001"
down_revision: Union[str, None] = "202606130001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "source_health",
        sa.Column("last_error", sa.String(length=1000), nullable=True),
    )
    op.add_column(
        "source_health",
        sa.Column("last_error_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "source_health",
        sa.Column("last_success_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("source_health", "last_success_at")
    op.drop_column("source_health", "last_error_at")
    op.drop_column("source_health", "last_error")
