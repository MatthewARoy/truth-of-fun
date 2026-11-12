"""Account-level data operations: export everything, delete everything.

Both exist because a person's data is theirs: they can take a copy, and they
can make the platform forget them (California's CCPA/CPRA gives residents
both rights; this product is built for the Bay Area).
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy import delete, update
from sqlmodel import Session, select

from app.models.agent_token import AgentToken
from app.models.event import Event
from app.models.itinerary import SavedItinerary
from app.models.password_reset import PasswordResetToken
from app.models.social import FolderInvite, FolderItem, FolderMember, FolderVote, VibeFolder
from app.models.user import User
from app.models.user_signal import UserSignal


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value is not None else None


def export_account(session: Session, user: User) -> dict[str, Any]:
    """Everything stored about *user*, as plain JSON-serialisable data.

    Credentials are described, never included: no password hash, no agent
    token secrets, no reset tokens.
    """
    user_id = int(user.id or 0)
    saved_ids = [int(i) for i in (user.saved_event_ids or [])]
    event_titles = {
        int(event_id): title
        for event_id, title in session.exec(
            select(Event.id, Event.title).where(Event.id.in_(saved_ids))
        ).all()
    } if saved_ids else {}

    folders = session.exec(select(VibeFolder).where(VibeFolder.user_id == user_id)).all()
    folder_ids = [int(folder.id) for folder in folders if folder.id is not None]
    items_by_folder: dict[int, list[dict[str, Any]]] = {folder_id: [] for folder_id in folder_ids}
    if folder_ids:
        for item, title in session.exec(
            select(FolderItem, Event.title)
            .join(Event, Event.id == FolderItem.event_id)
            .where(FolderItem.folder_id.in_(folder_ids))
        ).all():
            items_by_folder[int(item.folder_id)].append(
                {"event_id": item.event_id, "event_title": title, "added_at": _iso(item.created_at)}
            )

    return {
        "exported_at": _iso(datetime.now(timezone.utc)),
        "account": {
            "user_id": user_id,
            "email": user.email,
            "full_name": user.full_name,
            "created_at": _iso(user.created_at),
            "preferred_vibes": list(user.preferred_vibes or []),
        },
        "saved_events": [
            {"event_id": event_id, "title": event_titles.get(event_id)} for event_id in saved_ids
        ],
        "activity_signals": [
            {
                "type": signal.signal_type,
                "event_id": signal.event_id,
                "vibe_tag": signal.vibe_tag,
                "weight": signal.weight,
                "recorded_via": signal.created_via,
                "at": _iso(signal.created_at),
            }
            for signal in session.exec(
                select(UserSignal).where(UserSignal.user_id == user_id).order_by(UserSignal.id)
            ).all()
        ],
        "folders_owned": [
            {
                "folder_id": folder.id,
                "name": folder.name,
                "created_at": _iso(folder.created_at),
                "items": items_by_folder.get(int(folder.id or 0), []),
            }
            for folder in folders
        ],
        "folder_memberships": [
            {"folder_id": member.folder_id, "joined_at": _iso(member.created_at)}
            for member in session.exec(
                select(FolderMember).where(FolderMember.user_id == user_id)
            ).all()
        ],
        "folder_votes": [
            {"folder_item_id": vote.folder_item_id, "vote": vote.vote_value, "at": _iso(vote.updated_at)}
            for vote in session.exec(select(FolderVote).where(FolderVote.user_id == user_id)).all()
        ],
        "shared_itineraries": [
            {
                "title": plan.title,
                "request": plan.query,
                "planning_context": plan.planning_context,
                "stops": plan.stops,
                "created_at": _iso(plan.created_at),
                "expires_at": _iso(plan.expires_at),
                "revoked_at": _iso(plan.revoked_at),
            }
            for plan in session.exec(
                select(SavedItinerary).where(SavedItinerary.user_id == user_id)
            ).all()
        ],
        "agent_tokens": [
            {
                "name": token.name,
                "scopes": list(token.scopes or []),
                "created_at": _iso(token.created_at),
                "expires_at": _iso(token.expires_at),
                "revoked_at": _iso(token.revoked_at),
                "last_used_at": _iso(token.last_used_at),
            }
            for token in session.exec(select(AgentToken).where(AgentToken.user_id == user_id)).all()
        ],
    }


def delete_account(session: Session, user: User) -> None:
    """Remove *user* and everything that exists only because of them.

    Folders they own go with them (items, votes, members, invites); their
    votes and memberships in other people's folders are removed; their public
    itinerary links stop resolving. Caller commits.
    """
    user_id = int(user.id or 0)
    own_folder_ids = select(VibeFolder.id).where(VibeFolder.user_id == user_id)
    own_item_ids = select(FolderItem.id).where(FolderItem.folder_id.in_(own_folder_ids))
    doomed_invites = select(FolderInvite.id).where(
        (FolderInvite.created_by_user_id == user_id) | FolderInvite.folder_id.in_(own_folder_ids)
    )
    quiet = {"synchronize_session": False}

    session.execute(
        delete(FolderVote)
        .where((FolderVote.user_id == user_id) | FolderVote.folder_item_id.in_(own_item_ids))
        .execution_options(**quiet)
    )
    session.execute(
        delete(FolderMember)
        .where((FolderMember.user_id == user_id) | FolderMember.folder_id.in_(own_folder_ids))
        .execution_options(**quiet)
    )
    # Someone who joined another folder through an invite this user created
    # keeps their membership; only the pointer to the vanishing invite goes.
    session.execute(
        update(FolderMember)
        .where(FolderMember.invite_id.in_(doomed_invites))
        .values(invite_id=None)
        .execution_options(**quiet)
    )
    session.execute(delete(FolderInvite).where(FolderInvite.id.in_(doomed_invites)).execution_options(**quiet))
    session.execute(delete(FolderItem).where(FolderItem.folder_id.in_(own_folder_ids)).execution_options(**quiet))
    session.execute(delete(VibeFolder).where(VibeFolder.user_id == user_id).execution_options(**quiet))
    session.execute(delete(UserSignal).where(UserSignal.user_id == user_id).execution_options(**quiet))
    session.execute(delete(AgentToken).where(AgentToken.user_id == user_id).execution_options(**quiet))
    session.execute(delete(SavedItinerary).where(SavedItinerary.user_id == user_id).execution_options(**quiet))
    session.execute(
        delete(PasswordResetToken).where(PasswordResetToken.user_id == user_id).execution_options(**quiet)
    )
    session.execute(delete(User).where(User.id == user_id).execution_options(**quiet))
    session.expunge(user)
