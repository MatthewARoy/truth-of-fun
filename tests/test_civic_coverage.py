from datetime import date, datetime, timedelta, timezone

import pytest
from pydantic import ValidationError

from app.services.civic_coverage import CoverageManifest, OccurrenceExpectation, evaluate_occurrence

NOW = datetime(2026, 9, 30, 1, 42, tzinfo=timezone.utc)


def expectation(**changes):
    return OccurrenceExpectation(**dict(dict(key="african", series="YBG", expected_date=date(2026, 10, 3),
        title_aliases=["African Arts Festival"], venue_aliases=["Yerba Buena Gardens"],
        coverage_sources=["funcheap_sf", "sfstation"], evidence_url="https://ybgfestival.org/event/african-arts-festival-2026/",
        checked_at=NOW - timedelta(hours=2)), **changes))


def fresh_health():
    return {source: dict(status="healthy", last_run_at=NOW-timedelta(hours=1),
                        last_success_at=NOW-timedelta(hours=1), last_error=None)
            for source in ("funcheap_sf", "sfstation")}


def evaluate(item=None, events=None, health=None, **kwargs):
    return evaluate_occurrence(item or expectation(), events=events or [], health=health if health is not None else fresh_health(), now=NOW, **kwargs)


def event(**changes):
    # UTC Sunday is still the expected Saturday date in San Francisco.
    return dict(dict(id=42, title="6th Annual African Arts Festival", venue_name="Great Lawn, Yerba Buena Gardens",
                     start_at=datetime(2026, 10, 4, 1, tzinfo=timezone.utc), source_name="funcheap_sf", status="scheduled"), **changes)


def test_exact_occurrence_matches_venue_date_and_real_source():
    result = evaluate(events=[event()])
    assert result["status"] == "covered"
    assert result["event_ids"] == [42]
    assert result["stale_sources"] == []


@pytest.mark.parametrize("changes", [
    dict(title="Yerba Buena Gardens Festival season"), dict(source_name="dev-seed"),
    dict(title="Dev seed African Arts Festival"), dict(venue_name="Other park"),
    dict(start_at=datetime(2026,10,5,tzinfo=timezone.utc)), dict(status="cancelled")])
def test_umbrella_seed_wrong_venue_date_and_cancellation_do_not_satisfy(changes):
    assert evaluate(events=[event(**changes)])["status"] == "missing_current_corpus"


@pytest.mark.parametrize("changes", [dict(status="partial"), dict(last_error="parse failed"),
    dict(last_success_at=NOW-timedelta(days=3)), dict(last_run_at=NOW), dict(last_run_at=NOW+timedelta(hours=1))])
def test_incomplete_or_stale_corpus_cannot_claim_current_omission(changes):
    health = fresh_health()
    health["sfstation"].update(changes)
    result = evaluate(health=health)
    assert result["status"] == "corpus_stale"
    assert result["stale_sources"] == ["sfstation"]


def test_missing_health_and_old_success_before_official_check_are_stale():
    assert evaluate(health={})["status"] == "corpus_stale"
    health = fresh_health()
    health["funcheap_sf"]["last_success_at"] = NOW-timedelta(hours=3)
    assert evaluate(health=health)["status"] == "corpus_stale"


@pytest.mark.parametrize("changes,status", [
    (dict(checked_at=NOW-timedelta(days=15)),"expectation_stale"),
    (dict(checked_at=NOW+timedelta(minutes=1)),"expectation_stale"),
    (dict(expected_date=date(2026,8,1)),"past"),
    (dict(expected_date=date(2027,8,7)),"outside_horizon"),
    (dict(expected_date=None),"schedule_unverified"),
    (dict(expected_date=None,season_end=date(2026,9,1)),"off_season")])
def test_season_horizon_and_expectation_freshness_are_distinct(changes,status):
    assert evaluate(expectation(**changes))["status"] == status


def test_manifest_rejects_naive_evidence_empty_aliases_and_duplicate_keys():
    with pytest.raises(ValidationError):
        expectation(checked_at=NOW.replace(tzinfo=None))
    with pytest.raises(ValidationError):
        expectation(title_aliases=[" "])
    with pytest.raises(ValidationError):
        CoverageManifest(expectations=[expectation(),expectation()])


def test_public_snapshot_enforces_database_read_only():
    from sqlalchemy import create_engine, text
    from sqlalchemy.exc import DBAPIError
    from app.core.config import get_settings
    from conftest import _require_disposable_database
    from scripts.audit_civic_coverage import read_public_snapshot
    url = get_settings().database_url
    _require_disposable_database(url)
    engine = create_engine(url)
    try:
        with engine.connect() as connection:
            with connection.begin():
                events, health = read_public_snapshot(connection, now=NOW, horizon_days=180)
                assert isinstance(events,list) and isinstance(health,dict)
                assert connection.execute(text("SHOW transaction_read_only")).scalar_one() == "on"
                with pytest.raises(DBAPIError):
                    connection.execute(text("DELETE FROM events WHERE false"))
    finally:
        engine.dispose()
