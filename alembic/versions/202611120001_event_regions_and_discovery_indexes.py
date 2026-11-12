"""Event city/region columns and the indexes public discovery needs.

- ``events.city`` / ``events.region``: derived Bay Area geography (see
  app/services/regions.py). Left NULL here; the ingestion worker assigns
  existing rows at startup and after each cycle, so this migration stays a
  fast, metadata-only change.
- ``ix_events_scheduled_start``: the default feed is "scheduled events, by
  start time". The plain start_at index made that a walk from the oldest row
  ever ingested; this partial index holds only live rows.
- ``ix_events_location_geog``: every radius query casts the geometry to
  geography, which the geometry GiST index cannot serve. Without this a
  "near me" search is a sequential scan computing a distance per row.
- ``ix_events_status``: lifecycle sweeps and status filters.
"""
from alembic import op
import sqlalchemy as sa

revision = "202611120001"
down_revision = "202609290007"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("events", sa.Column("city", sa.String(length=100), nullable=True))
    op.add_column("events", sa.Column("region", sa.String(length=20), nullable=True))
    op.create_index("ix_events_city", "events", ["city"])
    op.create_index("ix_events_region", "events", ["region"])
    op.create_index("ix_events_status", "events", ["status"])
    op.execute(
        "CREATE INDEX ix_events_scheduled_start ON events (start_at, id) "
        "WHERE status = 'scheduled'"
    )
    op.execute(
        "CREATE INDEX ix_events_location_geog ON events USING gist ((location::geography))"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_events_location_geog")
    op.execute("DROP INDEX IF EXISTS ix_events_scheduled_start")
    op.drop_index("ix_events_status", table_name="events")
    op.drop_index("ix_events_region", table_name="events")
    op.drop_index("ix_events_city", table_name="events")
    op.drop_column("events", "region")
    op.drop_column("events", "city")
