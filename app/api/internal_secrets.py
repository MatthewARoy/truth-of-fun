from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlmodel import Session

from app.core.database import get_session
from app.core.security import InternalPrincipal, get_internal_principal, require_internal_scope
from app.services.secrets_store import KeyLease, SecretsStore, get_secrets_store
from app.services.key_usage_snapshots import snapshot_key_health as _snapshot_health

router = APIRouter(prefix="/internal/secrets", tags=["internal-secrets"])
logger = logging.getLogger(__name__)


def get_secrets_store_dependency() -> SecretsStore:
    return get_secrets_store()


class ActiveKeyResponse(BaseModel):
    provider: str
    key_id: str
    api_key: str
    usage_count: int
    quota_limit: int
    status: str
    source: str


class UsageReportRequest(BaseModel):
    key_id: str
    calls: int = Field(default=1, ge=0, le=10_000)
    last_status: int | None = None
    last_error: str | None = Field(default=None, max_length=1024)
    disable: bool = False


class UsageReportResponse(BaseModel):
    provider: str
    key_id: str
    updated: bool


class KeyHealthResponse(BaseModel):
    key_id: str
    usage_count: int
    quota_limit: int
    status: str
    last_status: int | None
    last_error: str | None
    updated_at_epoch: int


class ProviderHealthResponse(BaseModel):
    provider: str
    total_keys: int
    active_keys: int
    exhausted_keys: int
    disabled_keys: int
    keys: list[KeyHealthResponse]


@router.get(
    "/{provider}/active-key",
    response_model=ActiveKeyResponse,
    operation_id="internalGetActiveKey",
    summary="Lease the active API key for a provider (internal scope)",
    dependencies=[Depends(require_internal_scope("internal:secrets:read"))],
)
def get_active_key(
    provider: str,
    store: SecretsStore = Depends(get_secrets_store_dependency),
    _: InternalPrincipal = Depends(get_internal_principal),
) -> ActiveKeyResponse:
    try:
        lease: KeyLease = store.get_active_key(provider)
    except Exception as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return ActiveKeyResponse(
        provider=lease.provider,
        key_id=lease.key_id,
        api_key=lease.api_key,
        usage_count=lease.usage_count,
        quota_limit=lease.quota_limit,
        status=lease.status,
        source=lease.source,
    )


@router.post(
    "/{provider}/usage",
    response_model=UsageReportResponse,
    operation_id="internalReportKeyUsage",
    summary="Report API-key usage against a provider quota (internal scope)",
    dependencies=[Depends(require_internal_scope("internal:secrets:write"))],
)
def report_key_usage(
    provider: str,
    payload: UsageReportRequest,
    store: SecretsStore = Depends(get_secrets_store_dependency),
    session: Session = Depends(get_session),
    _: InternalPrincipal = Depends(get_internal_principal),
) -> UsageReportResponse:
    try:
        store.report_usage(
            provider=provider,
            key_id=payload.key_id,
            calls=payload.calls,
            last_status=payload.last_status,
            last_error=payload.last_error,
            disable=payload.disable,
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    try:
        _snapshot_health(
            provider=provider.strip().lower(),
            health_items=store.health(provider, key_id=payload.key_id),
            session=session,
        )
    except Exception:
        # Redis already accepted the usage. A telemetry failure must not make
        # clients retry and count the provider call twice.
        session.rollback()
        logger.warning("API-key usage accepted but its snapshot could not be recorded.", exc_info=True)
    return UsageReportResponse(provider=provider.strip().lower(), key_id=payload.key_id, updated=True)


@router.get(
    "/{provider}/health",
    response_model=ProviderHealthResponse,
    operation_id="internalGetProviderHealth",
    summary="Per-key quota health for a provider (internal scope)",
    dependencies=[Depends(require_internal_scope("internal:secrets:read"))],
)
def get_provider_health(
    provider: str,
    store: SecretsStore = Depends(get_secrets_store_dependency),
    _: InternalPrincipal = Depends(get_internal_principal),
) -> ProviderHealthResponse:
    items = store.health(provider)

    normalized = provider.strip().lower()
    active_count = sum(1 for item in items if item.status == "active")
    exhausted_count = sum(1 for item in items if item.status == "exhausted")
    disabled_count = sum(1 for item in items if item.status == "disabled")
    return ProviderHealthResponse(
        provider=normalized,
        total_keys=len(items),
        active_keys=active_count,
        exhausted_keys=exhausted_count,
        disabled_keys=disabled_count,
        keys=[
            KeyHealthResponse(
                key_id=item.key_id,
                usage_count=item.usage_count,
                quota_limit=item.quota_limit,
                status=item.status,
                last_status=item.last_status,
                last_error=item.last_error,
                updated_at_epoch=item.updated_at_epoch,
            )
            for item in items
        ],
    )
