"""Persist source identities and reusable, versioned vibe classifications."""

from alembic import op
import sqlalchemy as sa

revision = "202609290001"
down_revision = "202608240001"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "event_source_records",
        sa.Column("source_name", sa.String(100), primary_key=True),
        sa.Column("source_event_id", sa.String(255), primary_key=True),
        sa.Column("event_id", sa.Integer(), sa.ForeignKey("events.id", ondelete="CASCADE"), nullable=False),
        sa.Column("content_hash", sa.String(64), nullable=True),
    )
    op.create_index("ix_event_source_records_event_id", "event_source_records", ["event_id"])
    # Do not guess which of multiple existing rows an ambiguous identity owns.
    op.execute(sa.text("""
        INSERT INTO event_source_records (source_name, source_event_id, event_id)
        SELECT source_name, source_event_id, MIN(id)
          FROM events
         WHERE source_event_id IS NOT NULL AND source_event_id <> ''
           AND (
               source_name IN ('ticketmaster', 'meetup')
               OR (source_name = 'eventbrite' AND (source_event_id NOT LIKE 'http%' OR source_event_id LIKE '%/e/%'))
               OR (source_name = 'luma' AND source_event_id NOT LIKE 'http%' AND source_event_id NOT LIKE 'luma-%')
               OR (source_name = 'reddit' AND (source_event_id NOT LIKE 'http%' OR source_event_id LIKE '%/comments/%'))
           )
         GROUP BY source_name, source_event_id
        HAVING COUNT(*) = 1
    """))
    op.create_table(
        "vibe_tag_cache",
        sa.Column("cache_key", sa.String(64), primary_key=True),
        sa.Column("tags", sa.JSON(), nullable=False),
    )


def downgrade():
    op.drop_table("vibe_tag_cache")
    op.drop_index("ix_event_source_records_event_id", table_name="event_source_records")
    op.drop_table("event_source_records")
