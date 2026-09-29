"""Add scoped agent credentials and signal provenance without rewriting data."""
from alembic import op
import sqlalchemy as sa

revision = "202609290004"
down_revision = "202609290003"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table("agent_tokens",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("token_prefix", sa.String(12), nullable=False),
        sa.Column("token_hash", sa.String(64), nullable=False, unique=True),
        sa.Column("scopes", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True)),
        sa.Column("last_used_at", sa.DateTime(timezone=True)),
        sa.Column("request_count", sa.Integer(), nullable=False, server_default="0"))
    op.create_index("ix_agent_tokens_user_id", "agent_tokens", ["user_id"])
    op.create_index("ix_agent_tokens_token_prefix", "agent_tokens", ["token_prefix"], unique=True)
    op.add_column("user_signals", sa.Column("created_via", sa.String(64), nullable=False, server_default="legacy"))


def downgrade():
    op.drop_column("user_signals", "created_via")
    op.drop_table("agent_tokens")
