"""Initial schema with users/events and PostGIS.

Revision ID: 202603010001
Revises:
Create Date: 2026-03-01 00:01:00
"""

from typing import Sequence, Union

from alembic import op
import geoalchemy2
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "202603010001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS postgis;")

    op.create_table(
        "users",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("email", sa.String(length=255), nullable=False),
        sa.Column("hashed_password", sa.String(length=255), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("full_name", sa.String(length=255), nullable=True),
        sa.Column("role", sa.String(length=64), nullable=False, server_default="user"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("email"),
    )
    op.create_index(op.f("ix_users_email"), "users", ["email"], unique=True)

    op.create_table(
        "events",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("title", sa.String(length=500), nullable=False),
        sa.Column("description", sa.String(), nullable=True),
        sa.Column("start_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("end_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("source_name", sa.String(length=100), nullable=False),
        sa.Column("source_tier", sa.Integer(), nullable=False),
        sa.Column("source_event_id", sa.String(length=255), nullable=True),
        sa.Column("external_url", sa.String(length=2048), nullable=True),
        sa.Column("venue_name", sa.String(length=255), nullable=True),
        sa.Column("raw_address", sa.String(), nullable=True),
        sa.Column(
            "location",
            geoalchemy2.types.Geometry(geometry_type="POINT", srid=4326),
            nullable=False,
        ),
        sa.Column(
            "categories",
            sa.JSON(),
            nullable=False,
            server_default=sa.text("'[]'::json"),
        ),
        sa.Column(
            "tags",
            sa.JSON(),
            nullable=False,
            server_default=sa.text("'[]'::json"),
        ),
        sa.Column("price", sa.Numeric(precision=10, scale=2), nullable=True),
        sa.Column("currency", sa.String(length=3), nullable=True),
        sa.Column("image_url", sa.String(length=2048), nullable=True),
        sa.Column(
            "status",
            sa.String(length=50),
            nullable=False,
            server_default="scheduled",
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_events_source_event_id"), "events", ["source_event_id"], unique=False)
    op.create_index(op.f("ix_events_start_at"), "events", ["start_at"], unique=False)
    op.create_index(op.f("ix_events_title"), "events", ["title"], unique=False)
    op.execute("CREATE INDEX ix_events_location ON events USING GIST (location);")


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_events_location;")
    op.drop_index(op.f("ix_events_title"), table_name="events")
    op.drop_index(op.f("ix_events_start_at"), table_name="events")
    op.drop_index(op.f("ix_events_source_event_id"), table_name="events")
    op.drop_table("events")
    op.drop_index(op.f("ix_users_email"), table_name="users")
    op.drop_table("users")
