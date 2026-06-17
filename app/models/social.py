from datetime import datetime
from typing import Optional

from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Integer, String, UniqueConstraint, func
from sqlmodel import Field, SQLModel


class VibeFolder(SQLModel, table=True):
    __tablename__ = "vibe_folders"

    id: Optional[int] = Field(default=None, primary_key=True)
    user_id: int = Field(
        sa_column=Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    )
    name: str = Field(sa_column=Column(String(length=255), nullable=False))
    share_token: str = Field(
        sa_column=Column(String(length=64), nullable=False, unique=True, index=True)
    )
    created_at: datetime = Field(
        sa_column=Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    )
    updated_at: datetime = Field(
        sa_column=Column(
            DateTime(timezone=True),
            nullable=False,
            server_default=func.now(),
            onupdate=func.now(),
        )
    )


class FolderItem(SQLModel, table=True):
    __tablename__ = "folder_items"
    __table_args__ = (UniqueConstraint("folder_id", "event_id", name="uq_folder_event"),)

    id: Optional[int] = Field(default=None, primary_key=True)
    folder_id: int = Field(
        sa_column=Column(Integer, ForeignKey("vibe_folders.id"), nullable=False, index=True)
    )
    event_id: int = Field(
        sa_column=Column(Integer, ForeignKey("events.id"), nullable=False, index=True)
    )
    created_at: datetime = Field(
        sa_column=Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    )


class FolderVote(SQLModel, table=True):
    __tablename__ = "folder_votes"
    __table_args__ = (
        UniqueConstraint("folder_item_id", "user_id", name="uq_folder_item_user_vote"),
    )

    id: Optional[int] = Field(default=None, primary_key=True)
    folder_item_id: int = Field(
        sa_column=Column(Integer, ForeignKey("folder_items.id"), nullable=False, index=True)
    )
    user_id: int = Field(
        sa_column=Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    )
    vote_value: int = Field(sa_column=Column(Integer, nullable=False))
    created_at: datetime = Field(
        sa_column=Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    )
    updated_at: datetime = Field(
        sa_column=Column(
            DateTime(timezone=True),
            nullable=False,
            server_default=func.now(),
            onupdate=func.now(),
        )
    )


class FolderMember(SQLModel, table=True):
    """A user who joined a folder by accepting an invite; can view and vote."""

    __tablename__ = "folder_members"
    __table_args__ = (
        UniqueConstraint("folder_id", "user_id", name="uq_folder_member"),
    )

    id: Optional[int] = Field(default=None, primary_key=True)
    folder_id: int = Field(
        sa_column=Column(Integer, ForeignKey("vibe_folders.id"), nullable=False, index=True)
    )
    user_id: int = Field(
        sa_column=Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    )
    invite_id: Optional[int] = Field(
        default=None,
        sa_column=Column(Integer, ForeignKey("folder_invites.id"), nullable=True),
    )
    created_at: datetime = Field(
        sa_column=Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    )


class FolderInvite(SQLModel, table=True):
    __tablename__ = "folder_invites"

    id: Optional[int] = Field(default=None, primary_key=True)
    folder_id: int = Field(
        sa_column=Column(Integer, ForeignKey("vibe_folders.id"), nullable=False, index=True)
    )
    created_by_user_id: int = Field(
        sa_column=Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    )
    invite_token: str = Field(
        sa_column=Column(String(length=64), nullable=False, unique=True, index=True)
    )
    is_active: bool = Field(sa_column=Column(Boolean, nullable=False, server_default="true"))
    expires_at: Optional[datetime] = Field(
        default=None,
        sa_column=Column(DateTime(timezone=True), nullable=True),
    )
    created_at: datetime = Field(
        sa_column=Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    )
