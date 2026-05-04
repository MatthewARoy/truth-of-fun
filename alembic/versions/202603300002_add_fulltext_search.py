"""Add full-text search vector to events table."""

from alembic import op

revision = "202603300002"
down_revision = "202603300001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE events ADD COLUMN search_vector tsvector")
    op.execute("""
        CREATE OR REPLACE FUNCTION events_search_vector_update() RETURNS trigger AS $$
        BEGIN
            NEW.search_vector := to_tsvector('english',
                coalesce(NEW.title, '') || ' ' || coalesce(NEW.description, '')
            );
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
    """)
    op.execute("""
        CREATE TRIGGER events_search_vector_trigger
        BEFORE INSERT OR UPDATE OF title, description ON events
        FOR EACH ROW EXECUTE FUNCTION events_search_vector_update();
    """)
    # Backfill existing rows
    op.execute("""
        UPDATE events SET search_vector = to_tsvector('english',
            coalesce(title, '') || ' ' || coalesce(description, '')
        )
    """)
    op.execute("CREATE INDEX ix_events_search_vector ON events USING gin(search_vector)")


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_events_search_vector")
    op.execute("DROP TRIGGER IF EXISTS events_search_vector_trigger ON events")
    op.execute("DROP FUNCTION IF EXISTS events_search_vector_update()")
    op.execute("ALTER TABLE events DROP COLUMN IF EXISTS search_vector")
