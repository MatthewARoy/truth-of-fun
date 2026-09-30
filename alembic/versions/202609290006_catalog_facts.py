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


def downgrade():
    op.drop_column("events", "genres")
    op.drop_column("events", "performers")
