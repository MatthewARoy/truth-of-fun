"""Expire itinerary links and support owner revocation."""

from alembic import op
import sqlalchemy as sa

revision = "202609290002"
down_revision = "202609290001"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("saved_itineraries", sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("saved_itineraries", sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True))
    # Existing links receive a grace period from rollout, including old and
    # anonymous snapshots. Do not invent an owner or break all old links at once.
    # Raw prompts are removed from public serialization immediately by the API.
    op.execute(sa.text("UPDATE saved_itineraries SET expires_at = now() + interval '14 days'"))
    op.alter_column("saved_itineraries", "expires_at", nullable=False)


def downgrade():
    op.drop_column("saved_itineraries", "revoked_at")
    op.drop_column("saved_itineraries", "expires_at")
