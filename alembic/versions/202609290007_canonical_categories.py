"""Reversible legacy category repair with a frozen mapping; no paid inference."""
from alembic import op
import sqlalchemy as sa

from app.services.catalog_taxonomy_v1 import categories_v1, legacy_genres_v1

revision = "202609290007"
down_revision = "202609290006"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table("event_category_backup_20260929",
        sa.Column("event_id", sa.Integer(), sa.ForeignKey("events.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("categories", sa.JSON(), nullable=False),
        sa.Column("genres", sa.JSON(), nullable=False))
    conn = op.get_bind()
    events = sa.table("events", sa.column("id", sa.Integer()), sa.column("categories", sa.JSON()), sa.column("genres", sa.JSON()))
    backup = sa.table("event_category_backup_20260929", sa.column("event_id", sa.Integer()), sa.column("categories", sa.JSON()), sa.column("genres", sa.JSON()))
    # Stream/chunk a public catalog rather than materialize an unbounded corpus.
    for rows in conn.execute(sa.select(events).execution_options(stream_results=True, yield_per=500)).mappings().partitions(500):
        for row in rows:
            categories = categories_v1(row["categories"])
            genres = list(dict.fromkeys([*(row["genres"] or []), *legacy_genres_v1(row["categories"])]))
            if categories == row["categories"] and genres == row["genres"]:
                continue
            conn.execute(backup.insert().values(event_id=row["id"], categories=row["categories"], genres=row["genres"]))
            conn.execute(events.update().where(events.c.id == row["id"]).values(categories=categories, genres=genres))


def downgrade():
    conn = op.get_bind()
    conn.execute(sa.text("""UPDATE events SET categories=b.categories, genres=b.genres
        FROM event_category_backup_20260929 b WHERE events.id=b.event_id"""))
    op.drop_table("event_category_backup_20260929")
