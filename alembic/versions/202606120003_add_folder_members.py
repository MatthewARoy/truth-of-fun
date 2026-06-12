"""Add folder_members table so accepted invitees can view and vote.

Revision ID: 202606120003
Revises: 202606120002
Create Date: 2026-06-12
"""

from typing import Union

import sqlalchemy as sa
from alembic import op

revision: str = "202606120003"
down_revision: Union[str, None] = "202606120002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "folder_members",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "folder_id",
            sa.Integer(),
            sa.ForeignKey("vibe_folders.id"),
            nullable=False,
            index=True,
        ),
        sa.Column(
            "user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False, index=True
        ),
        sa.Column(
            "invite_id", sa.Integer(), sa.ForeignKey("folder_invites.id"), nullable=True
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.UniqueConstraint("folder_id", "user_id", name="uq_folder_member"),
    )


def downgrade() -> None:
    op.drop_table("folder_members")
