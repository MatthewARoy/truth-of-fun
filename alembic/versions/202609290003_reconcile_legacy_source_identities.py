"""Route legacy duplicate identities without deleting events or references."""

from alembic import op
import sqlalchemy as sa

revision = "202609290003"
down_revision = "202609290002"
branch_labels = None
depends_on = None


def upgrade():
    # Match the runtime's oldest-row policy. Keep established alias ownership,
    # every original event, and all votes/folder/signal references intact.
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
        ON CONFLICT (source_name, source_event_id) DO NOTHING
    """))


def downgrade():
    # Ownership learned during ingestion and seeded ownership are deliberately
    # indistinguishable. Retaining mappings is compatible with migration 002;
    # deleting them would lose provenance. Migration 001 owns table removal.
    pass
