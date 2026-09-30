"""Separate published performer/genre facts from canonical activity buckets."""
from alembic import op
import sqlalchemy as sa

revision = "202609290006"
down_revision = "202609290005"
branch_labels = None
depends_on = None


def upgrade():
    for name in ("performers", "genres"):
        op.add_column("events", sa.Column(name, sa.JSON(), nullable=False, server_default="[]"))
    op.add_column("event_source_records", sa.Column("hash_version", sa.Integer(), nullable=False, server_default="1"))
    op.add_column("event_source_records", sa.Column("catalog_facts", sa.JSON(), nullable=False, server_default="{}"))
    op.execute("CREATE INDEX ix_events_performers_search ON events USING gin (to_tsvector('english', performers::text))")


def downgrade():
    op.execute("DROP INDEX ix_events_performers_search")
    op.drop_column("event_source_records", "catalog_facts")
    op.drop_column("event_source_records", "hash_version")
    op.drop_column("events", "genres")
    op.drop_column("events", "performers")
