"""Add expires_at to folder_invites so invites can expire.

Revision ID: 202606130001
Revises: 202606120003
Create Date: 2026-06-13
"""

from typing import Union

import sqlalchemy as sa
from alembic import op

revision: str = "202606130001"
down_revision: Union[str, None] = "202606120003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "folder_invites",
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("folder_invites", "expires_at")
