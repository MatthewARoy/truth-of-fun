"""Add user_signals, vibe_folders, folder_items/invites/votes, and user profile columns.

Revision ID: 67ae74b20ec1
Revises: 202603300002
Create Date: 2026-05-04 17:09:58.078520
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "67ae74b20ec1"
down_revision: Union[str, None] = "202603300002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column("saved_event_ids", sa.JSON(), server_default="[]", nullable=False),
    )
    op.add_column(
        "users",
        sa.Column("preferred_vibes", sa.JSON(), server_default="[]", nullable=False),
    )

    op.create_table(
        "user_signals",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("event_id", sa.Integer(), nullable=True),
        sa.Column("signal_type", sa.String(length=64), nullable=False),
        sa.Column("vibe_tag", sa.String(length=128), nullable=True),
        sa.Column("weight", sa.Float(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["event_id"], ["events.id"]),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_user_signals_user_id", "user_signals", ["user_id"])
    op.create_index("ix_user_signals_event_id", "user_signals", ["event_id"])
    op.create_index("ix_user_signals_signal_type", "user_signals", ["signal_type"])

    op.create_table(
        "vibe_folders",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("share_token", sa.String(length=64), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_vibe_folders_user_id", "vibe_folders", ["user_id"])
    op.create_index(
        "ix_vibe_folders_share_token", "vibe_folders", ["share_token"], unique=True
    )

    op.create_table(
        "folder_invites",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("folder_id", sa.Integer(), nullable=False),
        sa.Column("created_by_user_id", sa.Integer(), nullable=False),
        sa.Column("invite_token", sa.String(length=64), nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default="true", nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["created_by_user_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["folder_id"], ["vibe_folders.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_folder_invites_folder_id", "folder_invites", ["folder_id"])
    op.create_index(
        "ix_folder_invites_created_by_user_id", "folder_invites", ["created_by_user_id"]
    )
    op.create_index(
        "ix_folder_invites_invite_token", "folder_invites", ["invite_token"], unique=True
    )

    op.create_table(
        "folder_items",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("folder_id", sa.Integer(), nullable=False),
        sa.Column("event_id", sa.Integer(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["event_id"], ["events.id"]),
        sa.ForeignKeyConstraint(["folder_id"], ["vibe_folders.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("folder_id", "event_id", name="uq_folder_event"),
    )
    op.create_index("ix_folder_items_folder_id", "folder_items", ["folder_id"])
    op.create_index("ix_folder_items_event_id", "folder_items", ["event_id"])

    op.create_table(
        "folder_votes",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("folder_item_id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("vote_value", sa.Integer(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["folder_item_id"], ["folder_items.id"]),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "folder_item_id", "user_id", name="uq_folder_item_user_vote"
        ),
    )
    op.create_index("ix_folder_votes_folder_item_id", "folder_votes", ["folder_item_id"])
    op.create_index("ix_folder_votes_user_id", "folder_votes", ["user_id"])


def downgrade() -> None:
    op.drop_index("ix_folder_votes_user_id", table_name="folder_votes")
    op.drop_index("ix_folder_votes_folder_item_id", table_name="folder_votes")
    op.drop_table("folder_votes")

    op.drop_index("ix_folder_items_event_id", table_name="folder_items")
    op.drop_index("ix_folder_items_folder_id", table_name="folder_items")
    op.drop_table("folder_items")

    op.drop_index("ix_folder_invites_invite_token", table_name="folder_invites")
    op.drop_index("ix_folder_invites_created_by_user_id", table_name="folder_invites")
    op.drop_index("ix_folder_invites_folder_id", table_name="folder_invites")
    op.drop_table("folder_invites")

    op.drop_index("ix_vibe_folders_share_token", table_name="vibe_folders")
    op.drop_index("ix_vibe_folders_user_id", table_name="vibe_folders")
    op.drop_table("vibe_folders")

    op.drop_index("ix_user_signals_signal_type", table_name="user_signals")
    op.drop_index("ix_user_signals_event_id", table_name="user_signals")
    op.drop_index("ix_user_signals_user_id", table_name="user_signals")
    op.drop_table("user_signals")

    op.drop_column("users", "preferred_vibes")
    op.drop_column("users", "saved_event_ids")
