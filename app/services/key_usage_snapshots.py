"""Bounded, best-effort durable telemetry for API and worker key usage."""
from __future__ import annotations

import hashlib
from datetime import datetime, timedelta, timezone

from sqlalchemy import delete, text
from sqlmodel import Session, select

from app.core.redaction import redact_secrets
from app.models.api_key import ApiKeyUsageSnapshot
from app.services.secrets_store import KeyHealth

_SNAPSHOT_INTERVAL = timedelta(hours=1)
_SNAPSHOT_RETENTION = timedelta(days=30)
_MAX_SNAPSHOTS_PER_KEY = 1000


def snapshot_key_health(
    *,
    provider: str,
    health_items: list[KeyHealth],
    session: Session,
) -> None:
    now = datetime.now(timezone.utc)
    for item in health_items:
        # Sampling is telemetry, so a busy sampler must never delay an already
        # accepted usage report. Only the current lock holder writes a sample.
        if session.get_bind().dialect.name == "postgresql":
            lock_id = int.from_bytes(
                hashlib.sha256(f"aaim-snapshot:{provider}:{item.key_id}".encode()).digest()[:8],
                "big", signed=True,
            )
            acquired = session.execute(
                text("SELECT pg_try_advisory_xact_lock(:lock_id)"), {"lock_id": lock_id}
            ).scalar_one()
            if not acquired:
                continue
        previous = session.exec(
            select(ApiKeyUsageSnapshot)
            .where(ApiKeyUsageSnapshot.provider == provider, ApiKeyUsageSnapshot.key_id == item.key_id)
            .order_by(ApiKeyUsageSnapshot.captured_at.desc(), ApiKeyUsageSnapshot.id.desc())
            .limit(1)
        ).first()
        if previous is not None:
            captured = previous.captured_at
            if captured.tzinfo is None:
                captured = captured.replace(tzinfo=timezone.utc)
            if previous.status == item.status and now - captured < _SNAPSHOT_INTERVAL:
                continue
        session.add(
            ApiKeyUsageSnapshot(
                provider=provider,
                key_id=item.key_id,
                usage_count=item.usage_count,
                quota_limit=item.quota_limit,
                status=item.status,
                last_status=item.last_status,
                last_error=redact_secrets(item.last_error),
                captured_at=now,
            )
        )
        session.flush()
        # Expired history is pruned during writes; reads remain side-effect free.
        session.execute(delete(ApiKeyUsageSnapshot).where(
            ApiKeyUsageSnapshot.provider == provider,
            ApiKeyUsageSnapshot.captured_at < now - _SNAPSHOT_RETENTION,
        ).execution_options(synchronize_session=False))
        excess = (
            select(ApiKeyUsageSnapshot.id)
            .where(ApiKeyUsageSnapshot.provider == provider, ApiKeyUsageSnapshot.key_id == item.key_id)
            .order_by(ApiKeyUsageSnapshot.captured_at.desc(), ApiKeyUsageSnapshot.id.desc())
            .offset(_MAX_SNAPSHOTS_PER_KEY)
        )
        session.execute(delete(ApiKeyUsageSnapshot).where(
            ApiKeyUsageSnapshot.id.in_(excess)
        ).execution_options(synchronize_session=False))
    session.commit()
