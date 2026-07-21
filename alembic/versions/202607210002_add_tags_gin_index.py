"""Index the JSONB containment used by GET /events?vibe_tag=.

``events.tags`` is a plain JSON column, so tag filtering casts it to JSONB and
uses the ``@>`` containment operator. With no index on that expression every
tag query was a sequential scan — and since the endpoint now also runs an
unpaginated COUNT for the X-Total-Count header, each request scanned the corpus
twice. This adds a GIN index on the same expression the query builds.

``jsonb_path_ops`` rather than the default operator class: it only supports
``@>`` (which is all this query uses) and is meaningfully smaller and faster
for it.

Revision ID: 202607210002
Revises: 202607210001
Create Date: 2026-07-21
"""

from typing import Union

from alembic import op

revision: str = "202607210002"
down_revision: Union[str, None] = "202607210001"
branch_labels = None
depends_on = None

# Must match app/api/discovery.py's cast(Event.tags, JSONB).contains(...)
# exactly, or the planner will not use the index.
_INDEX_SQL = (
    "CREATE INDEX ix_events_tags_jsonb ON events "
    "USING GIN ((tags::jsonb) jsonb_path_ops)"
)


def upgrade() -> None:
    op.execute(_INDEX_SQL)


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_events_tags_jsonb")
