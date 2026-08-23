"""add geocode_cache

Persistent cache of geocoding provider answers, successes and failures
alike, so a venue costs one rate-limited lookup rather than one per
six-hourly ingestion cycle.

Revision ID: 202608230001
Revises: 202608020001
Create Date: 2026-08-23
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "202608230001"
down_revision: Union[str, None] = "202608020001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "geocode_cache",
        sa.Column("query_key", sa.String(length=512), primary_key=True),
        sa.Column("provider", sa.String(length=32), nullable=False),
        sa.Column("lat", sa.Float(), nullable=True),
        sa.Column("lon", sa.Float(), nullable=True),
        sa.Column("confidence", sa.Float(), nullable=True),
        sa.Column("precision", sa.String(length=32), nullable=True),
        sa.Column("resolved", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("looked_up_at", sa.DateTime(timezone=True), nullable=False),
    )
    # Failure rows expire and are re-tried; this is the scan that finds them.
    op.create_index(
        "ix_geocode_cache_unresolved",
        "geocode_cache",
        ["looked_up_at"],
        postgresql_where=sa.text("resolved = false"),
    )


def downgrade() -> None:
    op.drop_index("ix_geocode_cache_unresolved", table_name="geocode_cache")
    op.drop_table("geocode_cache")
