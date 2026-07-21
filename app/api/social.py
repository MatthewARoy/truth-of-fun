from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Body, Depends, HTTPException, Response
from pydantic import BaseModel
from sqlalchemy import func
from sqlmodel import Session, select

from app.core.database import get_session
from app.core.security import get_current_user
from app.models.event import Event
from app.models.social import FolderInvite, FolderItem, FolderMember, FolderVote, VibeFolder
from app.models.user import User
from app.services.social import (
    DEFAULT_INVITE_TTL_DAYS,
    compute_invite_expiry,
    generate_share_token,
    is_invite_expired,
    is_valid_share_token,
    normalize_vote_value,
    upsert_vote_value,
)

router = APIRouter(tags=["social"])


class CreateFolderRequest(BaseModel):
    name: str


class AddFolderItemRequest(BaseModel):
    event_id: int


class VoteRequest(BaseModel):
    folder_item_id: int
    vote_value: int


class CreateInviteRequest(BaseModel):
    # Days until the invite expires. 0 or null creates a non-expiring invite.
    expires_in_days: int | None = DEFAULT_INVITE_TTL_DAYS


class FolderResponse(BaseModel):
    id: int
    name: str
    share_token: str
    created_at: datetime


class FolderItemResponse(BaseModel):
    folder_item_id: int
    event_id: int
    event_title: str
    vote_score: int


class FolderDetailResponse(BaseModel):
    id: int
    name: str
    share_token: str
    items: list[FolderItemResponse]


class InviteResponse(BaseModel):
    folder_id: int
    invite_token: str
    share_url: str
    expires_at: datetime | None


def _require_folder_owner(*, session: Session, folder_id: int, user_id: int) -> VibeFolder:
    folder = session.get(VibeFolder, folder_id)
    if folder is None:
        raise HTTPException(status_code=404, detail="Folder not found.")
    if folder.user_id != user_id:
        raise HTTPException(status_code=403, detail="You do not have access to this folder.")
    return folder


def _require_folder_access(*, session: Session, folder_id: int, user_id: int) -> VibeFolder:
    """Owner or accepted member: may view the folder and vote on its items."""
    folder = session.get(VibeFolder, folder_id)
    if folder is None:
        raise HTTPException(status_code=404, detail="Folder not found.")
    if folder.user_id == user_id:
        return folder
    membership = session.exec(
        select(FolderMember).where(
            FolderMember.folder_id == folder_id,
            FolderMember.user_id == user_id,
        )
    ).first()
    if membership is None:
        raise HTTPException(status_code=403, detail="You do not have access to this folder.")
    return folder


def _folder_items_with_votes(*, session: Session, folder_id: int) -> list[FolderItemResponse]:
    items = session.exec(select(FolderItem).where(FolderItem.folder_id == folder_id)).all()
    if not items:
        return []

    item_ids = [int(item.id or 0) for item in items]
    events = session.exec(select(Event).where(Event.id.in_([item.event_id for item in items]))).all()
    event_map = {int(event.id or 0): event for event in events}

    votes = session.exec(
        select(FolderVote.folder_item_id, func.sum(FolderVote.vote_value))
        .where(FolderVote.folder_item_id.in_(item_ids))
        .group_by(FolderVote.folder_item_id)
    ).all()
    vote_map = {int(folder_item_id): int(score or 0) for folder_item_id, score in votes}

    results: list[FolderItemResponse] = []
    for item in items:
        event = event_map.get(item.event_id)
        if event is None:
            continue
        item_id = int(item.id or 0)
        results.append(
            FolderItemResponse(
                folder_item_id=item_id,
                event_id=item.event_id,
                event_title=event.title,
                vote_score=vote_map.get(item_id, 0),
            )
        )

    results.sort(key=lambda row: (-row.vote_score, row.event_title))
    return results


@router.post(
    "/folders",
    response_model=FolderResponse,
    operation_id="createFolder",
    summary="Create a shortlist folder",
)
def create_folder(
    *,
    payload: CreateFolderRequest,
    session: Session = Depends(get_session),
    user: User = Depends(get_current_user),
) -> FolderResponse:
    name = payload.name.strip()
    if not name:
        raise HTTPException(status_code=400, detail="Folder name is required.")

    folder = VibeFolder(user_id=int(user.id or 0), name=name, share_token=generate_share_token())
    session.add(folder)
    session.commit()
    session.refresh(folder)
    return FolderResponse(
        id=int(folder.id or 0),
        name=folder.name,
        share_token=folder.share_token,
        created_at=folder.created_at,
    )


@router.get(
    "/folders",
    response_model=list[FolderResponse],
    operation_id="listFolders",
    summary="List the current user's folders",
)
def list_my_folders(
    *,
    session: Session = Depends(get_session),
    user: User = Depends(get_current_user),
) -> list[FolderResponse]:
    user_id = int(user.id or 0)
    member_folder_ids = select(FolderMember.folder_id).where(FolderMember.user_id == user_id)
    folders = session.exec(
        select(VibeFolder)
        .where((VibeFolder.user_id == user_id) | (VibeFolder.id.in_(member_folder_ids)))
        .order_by(VibeFolder.updated_at.desc())
    ).all()
    return [
        FolderResponse(
            id=int(folder.id or 0),
            name=folder.name,
            share_token=folder.share_token,
            created_at=folder.created_at,
        )
        for folder in folders
    ]


@router.post(
    "/folders/{folder_id}/items",
    response_model=FolderDetailResponse,
    operation_id="addFolderItem",
    summary="Add an event to a folder",
)
def add_folder_item(
    *,
    folder_id: int,
    payload: AddFolderItemRequest,
    session: Session = Depends(get_session),
    user: User = Depends(get_current_user),
) -> FolderDetailResponse:
    folder = _require_folder_owner(session=session, folder_id=folder_id, user_id=int(user.id or 0))

    event = session.get(Event, payload.event_id)
    if event is None:
        raise HTTPException(status_code=404, detail="Event not found.")

    existing = session.exec(
        select(FolderItem).where(
            FolderItem.folder_id == folder_id,
            FolderItem.event_id == payload.event_id,
        )
    ).first()
    if existing is None:
        session.add(FolderItem(folder_id=folder_id, event_id=payload.event_id))
        session.commit()

    items = _folder_items_with_votes(session=session, folder_id=folder_id)
    return FolderDetailResponse(
        id=int(folder.id or 0),
        name=folder.name,
        share_token=folder.share_token,
        items=items,
    )


@router.post(
    "/folders/{folder_id}/invite",
    response_model=InviteResponse,
    operation_id="createFolderInvite",
    summary="Mint an invite token for a folder",
)
def create_folder_invite(
    *,
    folder_id: int,
    payload: CreateInviteRequest | None = Body(default=None),
    session: Session = Depends(get_session),
    user: User = Depends(get_current_user),
) -> InviteResponse:
    folder = _require_folder_owner(session=session, folder_id=folder_id, user_id=int(user.id or 0))

    ttl_days = payload.expires_in_days if payload is not None else DEFAULT_INVITE_TTL_DAYS
    created_at = datetime.now(timezone.utc)
    invite = FolderInvite(
        folder_id=folder_id,
        created_by_user_id=int(user.id or 0),
        invite_token=generate_share_token(),
        is_active=True,
        expires_at=compute_invite_expiry(created_at=created_at, ttl_days=ttl_days),
    )
    session.add(invite)
    session.commit()
    session.refresh(invite)

    return InviteResponse(
        folder_id=folder_id,
        invite_token=invite.invite_token,
        share_url=f"/shared/folders/{folder.share_token}",
        expires_at=invite.expires_at,
    )


@router.delete(
    "/folders/{folder_id}/invites/{invite_token}",
    status_code=204,
    operation_id="revokeFolderInvite",
    summary="Revoke a folder invite",
)
def revoke_folder_invite(
    *,
    folder_id: int,
    invite_token: str,
    session: Session = Depends(get_session),
    user: User = Depends(get_current_user),
) -> Response:
    """Owner-only: deactivate an invite so the link can no longer be accepted."""
    _require_folder_owner(session=session, folder_id=folder_id, user_id=int(user.id or 0))

    invite = session.exec(
        select(FolderInvite).where(
            FolderInvite.invite_token == invite_token,
            FolderInvite.folder_id == folder_id,
        )
    ).first()
    if invite is None:
        raise HTTPException(status_code=404, detail="Invite not found.")

    if invite.is_active:
        invite.is_active = False
        session.add(invite)
        session.commit()
    return Response(status_code=204)


@router.post(
    "/folders/invites/{invite_token}/accept",
    response_model=FolderDetailResponse,
    operation_id="acceptFolderInvite",
    summary="Accept a folder invite",
)
def accept_folder_invite(
    *,
    invite_token: str,
    session: Session = Depends(get_session),
    user: User = Depends(get_current_user),
) -> FolderDetailResponse:
    invite = session.exec(
        select(FolderInvite).where(
            FolderInvite.invite_token == invite_token,
            FolderInvite.is_active == True,  # noqa: E712
        )
    ).first()
    if invite is None:
        raise HTTPException(status_code=404, detail="Invite not found or no longer active.")
    if is_invite_expired(invite.expires_at, now=datetime.now(timezone.utc)):
        raise HTTPException(status_code=410, detail="Invite has expired.")

    folder = session.get(VibeFolder, invite.folder_id)
    if folder is None:
        raise HTTPException(status_code=404, detail="Folder not found.")

    user_id = int(user.id or 0)
    if folder.user_id != user_id:
        existing = session.exec(
            select(FolderMember).where(
                FolderMember.folder_id == invite.folder_id,
                FolderMember.user_id == user_id,
            )
        ).first()
        if existing is None:
            session.add(
                FolderMember(
                    folder_id=invite.folder_id,
                    user_id=user_id,
                    invite_id=invite.id,
                )
            )
            session.commit()

    items = _folder_items_with_votes(session=session, folder_id=int(folder.id or 0))
    return FolderDetailResponse(
        id=int(folder.id or 0),
        name=folder.name,
        share_token=folder.share_token,
        items=items,
    )


@router.post(
    "/folders/{folder_id}/votes",
    response_model=FolderDetailResponse,
    operation_id="voteFolderItem",
    summary="Cast a soft-RSVP vote on a folder item",
)
def vote_on_folder_item(
    *,
    folder_id: int,
    payload: VoteRequest,
    session: Session = Depends(get_session),
    user: User = Depends(get_current_user),
) -> FolderDetailResponse:
    folder = _require_folder_access(session=session, folder_id=folder_id, user_id=int(user.id or 0))
    item = session.get(FolderItem, payload.folder_item_id)
    if item is None or item.folder_id != folder_id:
        raise HTTPException(status_code=404, detail="Folder item not found.")

    vote_value = normalize_vote_value(payload.vote_value)
    existing_vote = session.exec(
        select(FolderVote).where(
            FolderVote.folder_item_id == payload.folder_item_id,
            FolderVote.user_id == int(user.id or 0),
        )
    ).first()
    normalized_vote, changed = upsert_vote_value(
        existing_vote_value=existing_vote.vote_value if existing_vote else None,
        incoming_vote_value=vote_value,
    )
    if existing_vote is None:
        session.add(
            FolderVote(
                folder_item_id=payload.folder_item_id,
                user_id=int(user.id or 0),
                vote_value=normalized_vote,
            )
        )
    else:
        if changed:
            existing_vote.vote_value = normalized_vote
            session.add(existing_vote)

    if changed:
        session.commit()
    items = _folder_items_with_votes(session=session, folder_id=folder_id)
    return FolderDetailResponse(
        id=int(folder.id or 0),
        name=folder.name,
        share_token=folder.share_token,
        items=items,
    )


@router.get(
    "/folders/{folder_id}",
    response_model=FolderDetailResponse,
    operation_id="getFolder",
    summary="Get a folder with its items and votes",
)
def get_folder_detail(
    *,
    folder_id: int,
    session: Session = Depends(get_session),
    user: User = Depends(get_current_user),
) -> FolderDetailResponse:
    folder = _require_folder_access(session=session, folder_id=folder_id, user_id=int(user.id or 0))
    items = _folder_items_with_votes(session=session, folder_id=folder_id)
    return FolderDetailResponse(
        id=int(folder.id or 0),
        name=folder.name,
        share_token=folder.share_token,
        items=items,
    )


@router.get(
    "/shared/folders/{token}",
    response_model=FolderDetailResponse,
    operation_id="getSharedFolder",
    summary="Read a folder via its public share token",
)
def get_public_shared_folder(
    *,
    token: str,
    session: Session = Depends(get_session),
) -> FolderDetailResponse:
    if not is_valid_share_token(token):
        raise HTTPException(status_code=400, detail="Invalid token.")
    folder = session.exec(select(VibeFolder).where(VibeFolder.share_token == token)).first()
    if folder is None:
        raise HTTPException(status_code=404, detail="Shared folder not found.")
    items = _folder_items_with_votes(session=session, folder_id=int(folder.id or 0))
    return FolderDetailResponse(
        id=int(folder.id or 0),
        name=folder.name,
        share_token=folder.share_token,
        items=items,
    )
