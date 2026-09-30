"""Read-only dated-occurrence coverage evaluation; never generates recurrence."""
from __future__ import annotations

import re
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from pydantic import BaseModel, Field, HttpUrl, model_validator

SF = ZoneInfo("America/Los_Angeles")


class OccurrenceExpectation(BaseModel):
    key: str = Field(min_length=1, max_length=120)
    series: str = Field(min_length=1, max_length=200)
    expected_date: date | None = None
    title_aliases: list[str] = Field(min_length=1, max_length=10)
    venue_aliases: list[str] = Field(min_length=1, max_length=10)
    coverage_sources: list[str] = Field(min_length=1, max_length=10)
    evidence_url: HttpUrl
    checked_at: datetime
    season_start: date | None = None
    season_end: date | None = None
    admission_note: str = Field(default="Eligibility unverified", max_length=500)

    @model_validator(mode="after")
    def validate_evidence(self):
        if self.checked_at.tzinfo is None:
            raise ValueError("checked_at requires a timezone")
        for labels in (self.title_aliases, self.venue_aliases, self.coverage_sources):
            if any(not label.strip() or len(label) > 200 for label in labels):
                raise ValueError("aliases and sources must be bounded nonempty labels")
        if self.season_start and self.season_end and self.season_end < self.season_start:
            raise ValueError("season end precedes season start")
        return self


class CoverageManifest(BaseModel):
    version: int = Field(default=1, ge=1, le=1)
    expectations: list[OccurrenceExpectation] = Field(min_length=1, max_length=100)

    @model_validator(mode="after")
    def unique_keys(self):
        keys = [item.key for item in self.expectations]
        if len(keys) != len(set(keys)):
            raise ValueError("expectation keys must be unique")
        return self


def _aware(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value


def _contains(value: str | None, aliases: list[str]) -> bool:
    normalized = re.sub(r"\s+", " ", (value or "").casefold())
    return any(re.search(r"(?<!\w)" + re.escape(alias.strip().casefold()) + r"(?!\w)", normalized)
               for alias in aliases)


def evaluate_occurrence(expectation: OccurrenceExpectation, *, events: list[dict], health: dict[str, dict],
                        now: datetime, horizon_days: int = 180, evidence_days: int = 14,
                        corpus_hours: int = 24) -> dict:
    if now.tzinfo is None:
        raise ValueError("now requires a timezone")
    today = now.astimezone(SF).date()
    result = {"key": expectation.key, "series": expectation.series,
              "expected_date": str(expectation.expected_date) if expectation.expected_date else None,
              "evidence_url": str(expectation.evidence_url), "checked_at": expectation.checked_at.isoformat(),
              "admission_note": expectation.admission_note, "event_ids": [], "stale_sources": []}
    if ((expectation.season_start and today < expectation.season_start)
            or (expectation.season_end and today > expectation.season_end)):
        result["status"] = "off_season"
    elif expectation.expected_date and expectation.expected_date < today:
        result["status"] = "past"
    elif expectation.expected_date and expectation.expected_date > today + timedelta(days=horizon_days):
        result["status"] = "outside_horizon"
    elif not timedelta(0) <= now - expectation.checked_at <= timedelta(days=evidence_days):
        result["status"] = "expectation_stale"
    elif expectation.expected_date is None:
        result["status"] = "schedule_unverified"
    else:
        for source in expectation.coverage_sources:
            snapshot = health.get(source, {})
            success, run = _aware(snapshot.get("last_success_at")), _aware(snapshot.get("last_run_at"))
            # All named coverage paths need recent complete evidence. A newer
            # failed/partial run must not borrow the previous successful run.
            if (snapshot.get("status") != "healthy" or snapshot.get("last_error") or not success or not run
                    or not timedelta(0) <= now - success <= timedelta(hours=corpus_hours)
                    or run > now or success < run or success < expectation.checked_at):
                result["stale_sources"].append(source)
        for event in events:
            start = _aware(event.get("start_at"))
            if (start and start.astimezone(SF).date() == expectation.expected_date
                    and bool(event.get("source_name"))
                    and not re.search(r"(?:^|[-_])(?:dev|demo|seed|fixture|test)(?:$|[-_])", event.get("source_name") or "", re.I)
                    and event.get("status") == "scheduled"
                    and _contains(event.get("title"), expectation.title_aliases)
                    and _contains(event.get("venue_name"), expectation.venue_aliases)
                    and not re.search(r"\b(?:dev|demo|seed|fixture|test)\b", event.get("title") or "", re.I)):
                result["event_ids"].append(event["id"])
        result["status"] = ("covered" if result["event_ids"] else
                            "corpus_stale" if result["stale_sources"] else "missing_current_corpus")
    return result
