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
    return evaluate_occurrence(item or expectation(), events=events or [], health=health if health is not None else fresh_health(), now=NOW, source_horizon_days=kwargs.pop("source_horizon_days", {"funcheap_sf":10,"sfstation":7}), **kwargs)


def event(**changes):
    # UTC Sunday is still the expected Saturday date in San Francisco.
    return dict(dict(id=42, title="6th Annual African Arts Festival", venue_name="Great Lawn, Yerba Buena Gardens",
                     start_at=datetime(2026, 10, 4, 1, tzinfo=timezone.utc), source_name="funcheap_sf", status="scheduled"), **changes)


def test_exact_occurrence_matches_venue_date_and_real_source():
    result = evaluate(events=[event()])
    assert result["status"] == "covered"
    assert result["event_ids"] == [42]
    assert result["stale_sources"] == []


def test_any_real_ingestion_source_can_satisfy_stored_coverage():
    result = evaluate(events=[event(source_name="ticketmaster")], health={})
    assert result["status"] == "covered"
    assert result["event_ids"] == [42]
    assert result["stale_sources"] == ["funcheap_sf", "sfstation"]


@pytest.mark.parametrize("changes", [
    dict(title="Yerba Buena Gardens Festival season"), dict(source_name="dev-seed"),
    dict(source_name="unknown-provider"), dict(venue_name="Other park"),
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


def test_source_crawl_horizon_cannot_create_false_missing_alert():
    item = expectation(expected_date=date(2026,10,31))
    result = evaluate(item)
    assert result["status"] == "outside_source_horizon"
    assert result["outside_source_horizon"] == ["funcheap_sf", "sfstation"]
    assert evaluate(source_horizon_days={})["status"] == "coverage_horizon_unverified"


def test_only_sources_whose_configured_crawl_reaches_date_are_required():
    item = expectation(expected_date=date(2026,10,7))
    health = fresh_health();health.pop("sfstation")
    result = evaluate(item,health=health)
    assert result["outside_source_horizon"] == ["sfstation"]
    assert result["status"] == "missing_current_corpus"


def test_completion_timestamp_cannot_claim_an_extra_crawl_day():
    item = expectation(expected_date=date(2026,10,5), coverage_sources=["sfstation"])
    assert evaluate(item)["status"] == "outside_source_horizon"


def test_legitimate_demo_seed_test_title_is_not_a_dev_source():
    assert evaluate(events=[event(title="African Arts Festival: seed planting demo and taste test")])["status"] == "covered"


def test_manifest_matches_current_default_source_horizons():
    import inspect
    from pathlib import Path
    from app.ingestion.sources.dothebay import DoTheBaySource
    from app.ingestion.sources.sfstation import SFStationSource
    from app.ingestion.sources.eventbrite import EventbriteSource
    from app.ingestion.sources.funcheap_sf import FuncheapSFSource
    manifest = CoverageManifest.model_validate_json((Path(__file__).parents[1]/"docs/civic-expectations-2026-09-29.json").read_text())
    assert manifest.source_horizon_days == {"sfstation":SFStationSource.horizon_days,
        "dothebay":DoTheBaySource.horizon_days,"eventbrite":EventbriteSource.horizon_days,
        "funcheap_sf":inspect.signature(FuncheapSFSource.fetch_events).parameters["horizon_days"].default}


@pytest.mark.parametrize("offset",[0,180])
def test_expected_day_inclusive_global_horizon_boundaries(offset):
    from app.services.civic_coverage import SF
    from datetime import time
    day = NOW.astimezone(SF).date()+timedelta(days=offset)
    result = evaluate(expectation(expected_date=day),events=[event(start_at=datetime.combine(day,time(12),tzinfo=SF))])
    assert result["status"] == "covered"


def test_freshness_equality_and_future_season_boundary():
    health = fresh_health()
    for snapshot in health.values():
        snapshot["last_run_at"] = snapshot["last_success_at"] = expectation().checked_at
    assert evaluate(health=health)["status"] == "missing_current_corpus"
    assert evaluate(expectation(season_start=date(2026,10,1)))["status"] == "off_season"


class FakeEngine:
    dialect = type("Dialect",(),{"name":"postgresql"})()
    def connect(self): return self
    def begin(self): return self
    def __enter__(self): return self
    def __exit__(self,*args): return False
    def dispose(self): pass


@pytest.mark.parametrize("kind,code",[("missing",1),("covered",0),("stale",3),("outside",0)])
def test_cli_exit_contract(kind,code,tmp_path,monkeypatch,capsys):
    from scripts import audit_civic_coverage as script
    import json
    class Clock(datetime):
        @classmethod
        def now(cls,tz=None): return NOW
    monkeypatch.setattr(script,"datetime",Clock)
    monkeypatch.setenv("DATABASE_URL","postgresql+psycopg2://private-sentinel@localhost/unused")
    monkeypatch.setattr(script,"create_engine",lambda *a,**k:FakeEngine())
    monkeypatch.setattr(script,"read_public_snapshot",lambda *a,**k:([event()] if kind=="covered" else [], {} if kind=="stale" else fresh_health()))
    item = expectation(expected_date=date(2026,10,31)) if kind=="outside" else expectation()
    manifest = CoverageManifest(expectations=[item],source_horizon_days={"funcheap_sf":10,"sfstation":7})
    path = tmp_path/"manifest.json";path.write_text(manifest.model_dump_json())
    assert script.main(["--manifest",str(path)]) == code
    output = capsys.readouterr()
    assert "private-sentinel" not in output.out+output.err
    assert json.loads(output.out)["results"]


def test_cli_input_size_and_dialect_fail_without_credentials(tmp_path,monkeypatch,capsys):
    from scripts import audit_civic_coverage as script
    path = tmp_path/"manifest.json"
    path.write_text(" "*256001)
    monkeypatch.setenv("DATABASE_URL","sqlite:///secret-sentinel.db")
    assert script.main(["--manifest",str(path)]) == 2
    path.write_text(CoverageManifest(expectations=[expectation()]).model_dump_json())
    assert script.main(["--manifest",str(path)]) == 2
    path.write_text('{"expectations":[]}')
    assert script.main(["--manifest",str(path)]) == 2
    output = capsys.readouterr()
    assert "expectations" in output.err and "secret-sentinel" not in output.err+output.out


def test_snapshot_row_cap_is_failure_instead_of_truncated_missing_evidence():
    from scripts.audit_civic_coverage import read_public_snapshot
    class Result:
        def mappings(self):return [{}]*10001
    class Connection:
        def execute(self,*args):return Result()
    with pytest.raises(ValueError,match="10000"):
        read_public_snapshot(Connection(),now=NOW,horizon_days=180)
