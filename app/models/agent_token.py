"""Hashed, user-owned credentials for explicitly delegated agent access."""
from datetime import datetime

from sqlalchemy import JSON, Column, DateTime, ForeignKey, Integer, String, func
from sqlmodel import Field, SQLModel


class AgentToken(SQLModel, table=True):
    __tablename__ = "agent_tokens"

    id: int | None = Field(default=None, primary_key=True)
    user_id: int = Field(sa_column=Column(Integer, ForeignKey("users.id"), nullable=False, index=True))
    name: str = Field(sa_column=Column(String(100), nullable=False))
    token_prefix: str = Field(sa_column=Column(String(12), nullable=False, unique=True, index=True))
    token_hash: str = Field(sa_column=Column(String(64), nullable=False, unique=True))
    scopes: list[str] = Field(default_factory=list, sa_column=Column(JSON, nullable=False))
    created_at: datetime = Field(sa_column=Column(DateTime(timezone=True), nullable=False, server_default=func.now()))
    expires_at: datetime = Field(sa_column=Column(DateTime(timezone=True), nullable=False))
    revoked_at: datetime | None = Field(default=None, sa_column=Column(DateTime(timezone=True)))
    last_used_at: datetime | None = Field(default=None, sa_column=Column(DateTime(timezone=True)))
    request_count: int = Field(default=0, sa_column=Column(Integer, nullable=False, server_default="0"))
