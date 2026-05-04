"""Add API key inventory and usage snapshot tables.

Revision ID: 202603010002
Revises: 202603010001
Create Date: 2026-03-01 01:00:00
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "202603010002"
down_revision: Union[str, None] = "202603010001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "api_key_inventory",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("provider", sa.String(length=64), nullable=False),
        sa.Column("key_id", sa.String(length=128), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="active"),
        sa.Column("label", sa.String(length=255), nullable=True),
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
        sa.UniqueConstraint("key_id"),
    )
    op.create_index(
        op.f("ix_api_key_inventory_provider"),
        "api_key_inventory",
        ["provider"],
        unique=False,
    )
    op.create_index(
        op.f("ix_api_key_inventory_key_id"),
        "api_key_inventory",
        ["key_id"],
        unique=True,
    )

    op.create_table(
        "api_key_usage_snapshots",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("provider", sa.String(length=64), nullable=False),
        sa.Column("key_id", sa.String(length=128), nullable=False),
        sa.Column("usage_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("quota_limit", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="active"),
        sa.Column("last_status", sa.Integer(), nullable=True),
        sa.Column("last_error", sa.String(length=1024), nullable=True),
        sa.Column(
            "captured_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_api_key_usage_snapshots_provider"),
        "api_key_usage_snapshots",
        ["provider"],
        unique=False,
    )
    op.create_index(
        op.f("ix_api_key_usage_snapshots_key_id"),
        "api_key_usage_snapshots",
        ["key_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_api_key_usage_snapshots_captured_at"),
        "api_key_usage_snapshots",
        ["captured_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_api_key_usage_snapshots_captured_at"), table_name="api_key_usage_snapshots")
    op.drop_index(op.f("ix_api_key_usage_snapshots_key_id"), table_name="api_key_usage_snapshots")
    op.drop_index(op.f("ix_api_key_usage_snapshots_provider"), table_name="api_key_usage_snapshots")
    op.drop_table("api_key_usage_snapshots")
    op.drop_index(op.f("ix_api_key_inventory_key_id"), table_name="api_key_inventory")
    op.drop_index(op.f("ix_api_key_inventory_provider"), table_name="api_key_inventory")
    op.drop_table("api_key_inventory")
