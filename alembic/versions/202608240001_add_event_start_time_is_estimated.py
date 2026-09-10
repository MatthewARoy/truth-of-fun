"""Mark events whose wall-clock start time is a connector placeholder.

Eventbrite listing pages publish a calendar date but usually no time, so the
connector stamps 19:00 SF-local. Stored bare, that placeholder reads as fact:
it broke dedupe against sources that had the real hour, and produced an
"R&B Brunch" at 7 PM. The flag lets dedupe, the API and the UI tell the
difference.

Revision ID: 202608230001
Revises: 202608020001
Create Date: 2026-08-23
"""

from typing import Union

import sqlalchemy as sa
from alembic import op

revision: str = "202608240001"
down_revision: Union[str, None] = "202608230001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "events",
        sa.Column(
            "start_time_is_estimated",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )
    # Backfill the rows the placeholder already produced. Every Eventbrite row
    # sitting at exactly 19:00 SF-local was written by DEFAULT_EVENT_HOUR --
    # the connector has never parsed a time -- so leaving them unflagged would
    # keep asserting a precision the source never gave us. A genuine 19:00
    # Eventbrite start re-flags itself to false on the next ingest cycle.
    op.execute(
        sa.text(
            """
            UPDATE events
               SET start_time_is_estimated = true
             WHERE source_name = 'eventbrite'
               AND EXTRACT(
                     HOUR FROM (start_at AT TIME ZONE 'America/Los_Angeles')
                   ) = 19
               AND EXTRACT(
                     MINUTE FROM (start_at AT TIME ZONE 'America/Los_Angeles')
                   ) = 0
            """
        )
    )


def downgrade() -> None:
    op.drop_column("events", "start_time_is_estimated")
