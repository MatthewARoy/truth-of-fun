"""Preserve explicitly public origin and travel mode in itinerary snapshots."""
from alembic import op
import sqlalchemy as sa

revision = "202609290005"
down_revision = "202609290004"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("saved_itineraries", sa.Column("planning_context", sa.JSON(), nullable=False, server_default="{}"))


def downgrade():
    op.drop_column("saved_itineraries", "planning_context")
