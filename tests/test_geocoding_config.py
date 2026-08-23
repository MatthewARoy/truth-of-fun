"""Which geocoder a deployment gets, and what happens with none configured.

Nominatim is free and needs no key; Google and Mapbox need billing. Rather
than pick for the operator, the provider is a setting — and leaving it
unset must be a supported state, not a broken one, because that is what
every existing deployment and every test run looks like.
"""

from __future__ import annotations

from app.core.config import Settings
from app.services.geocoding import NominatimProvider, build_geocoder


def test_no_provider_configured_still_yields_a_working_geocoder() -> None:
    """Ingestion must not depend on a geocoder being configured: the result
    still resolves the static table and simply never calls out."""
    geocoder = build_geocoder(Settings(geocoding_provider=None))

    assert geocoder is not None
    assert geocoder.provider is None


def test_nominatim_is_selected_by_name() -> None:
    geocoder = build_geocoder(Settings(geocoding_provider="nominatim"))

    assert isinstance(geocoder.provider, NominatimProvider)


def test_an_unrecognised_provider_disables_geocoding_rather_than_crashing() -> None:
    """A typo in an env var must not take the ingestion worker down."""
    geocoder = build_geocoder(Settings(geocoding_provider="gogle"))

    assert geocoder.provider is None


def test_settings_carry_the_provider_limits_into_the_geocoder() -> None:
    geocoder = build_geocoder(
        Settings(
            geocoding_provider="nominatim",
            geocoding_max_lookups_per_run=7,
            geocoding_failure_retry_days=3,
        )
    )

    assert geocoder.max_lookups_per_run == 7
    assert geocoder.failure_retry_days == 3


def test_the_ingestion_worker_geocodes_by_default() -> None:
    """Wiring check: geocoding is worthless if the worker never gets one."""
    from app.worker import IngestionWorker

    worker = IngestionWorker(session_factory=lambda: None, source_registry=object())

    assert worker._pipeline_service._geocoder is not None
