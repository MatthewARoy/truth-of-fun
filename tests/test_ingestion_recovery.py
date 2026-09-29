"""Recovery at the fetch -> durable processing -> checkpoint boundary."""
from __future__ import annotations

import asyncio
from contextlib import nullcontext
from typing import Any

import httpx
import pytest
from sqlmodel import Session, create_engine

from app.ingestion import ticketmaster as tm
from app.ingestion.ticketmaster import TicketmasterSource
from app.models.geocode_cache import GeocodeCacheEntry
from app.models.source_health import SourceHealthRecord
from app.services.geocoding import NominatimProvider, VenueGeocoder
from app.worker import IngestionWorker, _source_health_state

pytestmark = pytest.mark.anyio


@pytest.fixture(autouse=True)
def offline_worker(monkeypatch):
    from app.services.secrets_store import NoopSecretsStore
    from app.core.config import Settings
    store = NoopSecretsStore(settings=Settings(_env_file=None, aaim_fallback_to_env=False))
    monkeypatch.setattr('app.worker.get_secrets_store', lambda: store)
    async def alert(**kwargs):
        return None
    monkeypatch.setattr('app.worker.send_alert', alert)
    _source_health_state.clear()


async def test_capped_ticketmaster_window_is_incomplete_and_cannot_checkpoint(tmp_path, monkeypatch):
    path = tmp_path / 'sync.json'
    monkeypatch.setattr(tm, '_SYNC_STATE_PATH', path)
    source = TicketmasterSource(api_key='fixture')
    async def page(params):
        return {'page': {'totalPages': 6, 'totalElements': 1200}, '_embedded': {'events': []}}
    monkeypatch.setattr(source, '_fetch_page', page)
    await source.fetch_events()
    assert source.last_fetch_error and 'cap' in source.last_fetch_error.lower()
    source.acknowledge_persisted()
    assert not path.exists()


async def test_ticketmaster_does_not_claim_undocumented_incremental_filter(tmp_path, monkeypatch):
    monkeypatch.setattr(tm, '_SYNC_STATE_PATH', tmp_path / 'sync.json')
    tm._save_last_sync_timestamp('2026-01-01T00:00:00Z')
    source = TicketmasterSource(api_key='fixture')
    seen = []
    async def page(params):
        seen.append(dict(params))
        return {'page': {'totalPages': 0, 'totalElements': 0}}
    monkeypatch.setattr(source, '_fetch_page', page)
    await source.fetch_events()
    assert 'modifiedDate' not in seen[0]
    assert tm._load_last_sync_timestamp() == '2026-01-01T00:00:00Z'
    source.acknowledge_persisted()
    assert tm._load_last_sync_timestamp() != '2026-01-01T00:00:00Z'


class _Source:
    source_name = 'fixture'
    last_fetch_was_incremental = False
    def __init__(self):
        self.acknowledged = False
    async def fetch_events(self):
        return [{'title': 'fixture'}]
    async def close(self):
        pass
    def acknowledge_persisted(self):
        self.acknowledged = True


class _Registry:
    def __init__(self, source):
        self.source = source
    def list_sources(self):
        return ['fixture']
    def create(self, _name):
        return self.source


async def test_pipeline_failure_persists_failed_health_and_alerts_without_checkpoint(monkeypatch):
    engine = create_engine('sqlite://')
    SourceHealthRecord.__table__.create(engine)
    class Pipeline:
        async def process_raw_events(self, **kwargs):
            raise RuntimeError('database commit failed')
    alerts = []
    async def alert(**kwargs):
        alerts.append(kwargs)
    monkeypatch.setattr('app.worker.send_alert', alert)
    source = _Source()
    worker = IngestionWorker(source_registry=_Registry(source), pipeline_service=Pipeline(),
        session_factory=lambda: Session(engine), quota_window_hours=0)
    with pytest.raises(RuntimeError, match='database commit failed'):
        await worker.run_once()
    assert not source.acknowledged
    with Session(engine) as session:
        health = session.get(SourceHealthRecord, 'fixture')
        assert health is not None and health.status == 'failing'
        assert 'database commit failed' in health.last_error
        assert health.last_success_at is None
    assert alerts
    engine.dispose()


async def test_worker_loop_retries_after_recoverable_failure(monkeypatch):
    worker = IngestionWorker(pipeline_service=object(), run_interval_seconds=7)
    calls = []
    sleeps = []
    async def run_once():
        calls.append(1)
        if len(calls) == 1:
            raise RuntimeError('temporary failure')
        raise asyncio.CancelledError
    async def sleep(seconds):
        sleeps.append(seconds)
    monkeypatch.setattr(worker, 'run_once', run_once)
    monkeypatch.setattr('app.worker.asyncio.sleep', sleep)
    with pytest.raises(asyncio.CancelledError):
        await worker.run_forever()
    assert len(calls) == 2
    assert sleeps == [7]


async def test_successful_empty_incremental_fetch_is_healthy_and_checkpointed():
    class Delta(_Source):
        last_fetch_was_incremental = True
        async def fetch_events(self):
            return []
    class Pipeline:
        async def process_raw_events(self, **kwargs):
            return {'inserted': 0, 'updated': 0, 'skipped': 0}
    source = Delta()
    worker = IngestionWorker(source_registry=_Registry(source), pipeline_service=Pipeline(),
        session_factory=lambda: nullcontext(object()), quota_window_hours=0)
    await worker.run_once()
    await worker.run_once()
    assert _source_health_state['fixture']['status'] == 'healthy'
    assert _source_health_state['fixture']['last_success_at'] is not None
    assert source.acknowledged


@pytest.mark.parametrize('failure', ['http', 'transport', 'malformed'])
async def test_transient_geocoder_failure_is_not_cached_as_a_month_long_miss(failure):
    calls = []
    def handler(request):
        calls.append(request)
        if len(calls) == 1:
            if failure == 'transport':
                raise httpx.ConnectError('fixture unavailable', request=request)
            if failure == 'malformed':
                return httpx.Response(200, json={'error': 'unexpected response'})
            return httpx.Response(503)
        return httpx.Response(200, json=[{
            'lat': '37.81', 'lon': '-122.27', 'place_rank': 30,
        }])
    class NoWait:
        async def acquire(self):
            pass
    engine = create_engine('sqlite://')
    GeocodeCacheEntry.__table__.create(engine)
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        geocoder = VenueGeocoder(provider=NominatimProvider(client=client, rate_limiter=NoWait()))
        with Session(engine) as session:
            first = await geocoder.resolve(session=session, venue_name='New Space', raw_address=None, city='Oakland')
            assert first is None
            second = await geocoder.resolve(session=session, venue_name='New Space', raw_address=None, city='Oakland')
            assert second is not None
    assert len(calls) == 2
    engine.dispose()


@pytest.mark.parametrize('rejected', [0, 1])
async def test_checkpoint_happens_after_pipeline_completion_and_never_for_rejected_rows(rejected):
    source = _Source()
    calls = []
    class Pipeline:
        async def process_raw_events(self, **kwargs):
            assert not source.acknowledged
            calls.append('committed')
            # skipped means an existing unchanged event, which is safe to ack.
            return {'inserted': 0, 'updated': 0, 'skipped': 1, 'rejected': rejected}
    original_ack = source.acknowledge_persisted
    def acknowledge():
        assert calls == ['committed']
        original_ack()
    source.acknowledge_persisted = acknowledge
    worker = IngestionWorker(source_registry=_Registry(source), pipeline_service=Pipeline(),
        session_factory=lambda: nullcontext(object()), quota_window_hours=0)
    await worker.run_once()
    assert source.acknowledged is (rejected == 0)
    assert _source_health_state['fixture']['status'] == ('failing' if rejected else 'healthy')


async def test_input_agent_extraction_failures_are_exposed_to_worker():
    from app.ingestion.input_agent import InputAgentSource
    class Source(InputAgentSource):
        source_name = 'fixture'
        source_tier = 2
        async def discover_candidates(self, **kwargs):
            self.last_fetch_error = "calendar page cap reached"
            return ['broken']
        async def extract_candidate(self, candidate):
            raise TimeoutError('fixture')
        def normalize_raw(self, raw_item):
            return None
    source = Source()
    try:
        assert await source.fetch_events() == []
        assert source.last_fetch_error and 'TimeoutError' in source.last_fetch_error
        assert 'calendar page cap reached' in source.last_fetch_error
    finally:
        await source.close()


def test_ticketmaster_cannot_bypass_disabled_aaim_inventory_with_environment_key(monkeypatch):
    from app.core.config import Settings
    settings = Settings(_env_file=None, aaim_enabled=True, ticketmaster_api_key='fixture-env')
    class DisabledInventory:
        def get_active_key(self, provider):
            raise RuntimeError('No active API keys available')
    monkeypatch.setattr(tm, 'get_settings', lambda: settings)
    monkeypatch.setattr(tm, 'get_secrets_store', lambda: DisabledInventory())
    with pytest.raises(RuntimeError, match='No active API keys'):
        TicketmasterSource()


async def test_worker_with_aaim_disabled_does_not_touch_redis(monkeypatch):
    from app.core.config import Settings
    monkeypatch.setattr('app.worker.get_settings', lambda: Settings(_env_file=None, aaim_enabled=False))
    def unexpected_store():
        pytest.fail('disabled AAIM must not access Redis')
    monkeypatch.setattr('app.worker.get_secrets_store', unexpected_store)
    class Source(_Source):
        source_name = 'ticketmaster'
    class Registry(_Registry):
        def list_sources(self):
            return ['ticketmaster']
    class Pipeline:
        async def process_raw_events(self, **kwargs):
            return {'inserted':1}
    worker = IngestionWorker(source_registry=Registry(Source()), pipeline_service=Pipeline(),
        session_factory=lambda: nullcontext(object()))
    await worker.run_once()


@pytest.mark.parametrize('pipeline_fails', [False, True])
async def test_worker_samples_the_used_key_once_per_cycle_even_when_event_processing_fails(
    tmp_path, monkeypatch, pipeline_fails
):
    from app.core.config import Settings
    from app.models.api_key import ApiKeyUsageSnapshot
    from app.services.secrets_store import KeyHealth, KeyLease
    from sqlmodel import select

    settings = Settings(_env_file=None, aaim_enabled=True)
    class Store:
        def __init__(self):
            self.health_calls = 0
            self.rows = [
                KeyHealth(key_id=key, usage_count=0, quota_limit=100, status='active',
                    last_status=200, last_error=None, updated_at_epoch=1)
                for key in ('used-key', 'unused-key')
            ]
        def get_active_key(self, provider):
            return KeyLease(provider=provider, key_id='used-key', api_key='fixture',
                usage_count=0, quota_limit=100, status='active', source='redis')
        def report_usage(self, **kwargs):
            assert kwargs['key_id'] == 'used-key'
            self.rows[0].usage_count += kwargs['calls']
        def health(self, provider):
            self.health_calls += 1
            return self.rows
    store = Store()
    monkeypatch.setattr(tm, 'get_settings', lambda: settings)
    monkeypatch.setattr(tm, 'get_secrets_store', lambda: store)
    monkeypatch.setattr(tm, '_SYNC_STATE_PATH', tmp_path / 'sync.json')
    monkeypatch.setattr('app.worker.get_settings', lambda: settings)
    monkeypatch.setattr('app.worker.get_secrets_store', lambda: store)
    source = TicketmasterSource()
    import httpx
    source._client = httpx.AsyncClient(transport=httpx.MockTransport(
        lambda request: httpx.Response(200, json={'page': {'totalPages': 0, 'totalElements': 0}})
    ))
    class Registry:
        def list_sources(self):
            return ['ticketmaster']
        def create(self, _):
            return source
    class Pipeline:
        async def process_raw_events(self, **kwargs):
            if pipeline_fails:
                raise RuntimeError('fixture event transaction failure')
            return {'inserted':0}
    engine = create_engine('sqlite://')
    ApiKeyUsageSnapshot.__table__.create(engine)
    SourceHealthRecord.__table__.create(engine)
    worker = IngestionWorker(source_registry=Registry(), pipeline_service=Pipeline(),
        session_factory=lambda: Session(engine), quota_window_hours=0)
    try:
        for _ in range(2):
            if pipeline_fails:
                with pytest.raises(RuntimeError, match='event transaction failure'):
                    await worker.run_once()
            else:
                await worker.run_once()
        with Session(engine) as session:
            snapshots = session.exec(select(ApiKeyUsageSnapshot)).all()
            assert len(snapshots) == 1
            assert snapshots[0].key_id == 'used-key'
            assert snapshots[0].usage_count == 3  # Dated search plus TBA and TBD passes.
        assert store.rows[0].usage_count == 6  # Three requests in each of two cycles.
        assert store.health_calls == 2
    finally:
        engine.dispose()
