"""Localist connector (Stanford, SJSU): public-interest filter and normalisation.

Every row below is trimmed from the live feeds
(``https://events.stanford.edu/api/2/events?days=14&pp=100&page=1`` and the
same path on ``events.sjsu.edu``), captured 2026-11-12: unused keys dropped,
descriptions shortened, one person's name replaced. Rows marked "variant"
change one field of a real row to isolate a rule. Nothing touches the network;
paged crawls are served through ``httpx.MockTransport``.
"""

from __future__ import annotations

import copy
from datetime import date, datetime, timezone
from typing import Any

import httpx
import pytest

from app.ingestion import registry
from app.ingestion.sources._calendar_common import USER_AGENT
from app.ingestion.sources.localist import LocalistSource
from app.ingestion.sources.localist import SJSUEventsSource
from app.ingestion.sources.localist import StanfordEventsSource
from app.services.catalog_taxonomy_v1 import categories_v1
from app.services.tags import canonical_vibe_tags

pytestmark = pytest.mark.anyio

TODAY = date(2026, 11, 12)
STANFORD_API = "https://events.stanford.edu/api/2/events"
NO_GEO = {"latitude": None, "longitude": None, "street": None, "city": None, "state": None, "zip": None}


def _row(
    event_id: int,
    title: str,
    slug: str,
    instance: tuple[int, str, str | None, bool],
    *,
    types: tuple[str, ...] = (),
    audience: tuple[str, ...] | None = None,
    audience_key: str = "event_audience",
    site: str = "https://events.stanford.edu",
    **fields: Any,
) -> dict[str, Any]:
    """One ``{"event": {...}}`` row in the live shape, with only the keys the connector reads."""
    filters: dict[str, Any] = {}
    if types:
        filters["event_types"] = [{"name": name} for name in types]
    if audience is not None:
        filters[audience_key] = [{"name": name} for name in audience]
    instance_id, start, end, all_day = instance
    event = {
        "id": event_id,
        "title": title,
        "localist_url": f"{site}/event/{slug}",
        "location_name": "",
        "address": "",
        "status": "live",
        "experience": "inperson",
        "private": False,
        "recurring": False,
        "free": False,
        "ticket_cost": None,
        "description_text": "",
        "photo_url": None,
        "geo": dict(NO_GEO),
        "departments": [],
        "filters": filters,
        "event_instances": [
            {"event_instance": {"id": instance_id, "start": start, "end": end, "all_day": all_day}}
        ],
    }
    event.update(fields)
    return {"event": event}


# --- Stanford ---------------------------------------------------------------

BAROQUE_RECITAL = _row(
    54364839338499,
    "Stanford Baroque Recital",
    "stanford-baroque-recital",
    (54364856936678, "2026-11-12T12:00:00-08:00", "2026-11-12T13:00:00-08:00", False),
    types=("Performance",),
    audience=("Everyone", "General Public"),
    location_name="Braun Music Center",
    address="541 Lasuen Mall, Stanford, CA 94305",
    free=True,
    ticket_cost="Free Admission",
    description_text=(
        "Stanford harpsichordists, recorder players, and singers will perform baroque "
        "music by Handel, Byrd, Purcell, and more.\n\nAdmission Information\n\nFree admission"
    ),
    photo_url="https://localist-images.azureedge.net/photos/54364839128576/huge/88fcbf0a3e734e200fca830eb84dc8bac712f008.jpg",
    geo={"latitude": "37.423758", "longitude": "-122.169296", "street": "541 Lasuen Mall",
         "city": "Stanford", "state": "CA", "zip": "94305"},
    departments=[{"name": "Department of Music"}],
)

OUR_TOWN = _row(
    53763766608135,
    "MAIN STAGE | Our Town",
    "our-town",
    (53763779186531, "2026-11-12T20:00:00-08:00", "2026-11-12T21:30:00-08:00", False),
    types=("Performance",),  # no audience filter on this row at all
    location_name="Roble Gym",
    address="375 Santa Teresa Street, Stanford, CA 94305",
    ticket_cost="$5-$21.90",
    geo={"latitude": "37.426008", "longitude": "-122.174909", "street": "375 Santa Teresa Street",
         "city": "Stanford", "state": "CA", "zip": "94305"},
    departments=[{"name": "Department of Theater & Performance Studies"}],
)

HYBRID_TALK = _row(
    53879093950767,
    "How to Fix a Broken Hierarchy",
    "how-to-fix-a-broken-hierarchy",
    (53879093950768, "2026-11-12T12:00:00-08:00", "2026-11-12T13:00:00-08:00", False),
    types=("Lecture/Presentation/Talk",),
    audience=("Everyone",),
    experience="hybrid",
    location_name="GSB Knight - Class of 1968",
    ticket_cost="",
    geo={"latitude": "37.427663", "longitude": "-122.162043", "street": "653 Jane Stanford Way",
         "city": "Stanford", "state": "CA", "zip": "94305"},
)

# A months-long exhibition is one all-day row per day, each with its own instance id.
EXHIBITION_DAY_1 = _row(
    52881224936195,
    "Carolyn Lazard: Long Take",
    "carolyn-lazard-long-take",
    (52881225062246, "2026-11-12T00:00:00-08:00", None, True),
    types=("Exhibition",),
    audience=("Everyone",),
    recurring=True,
    location_name="Cantor Arts Center",
    address="328 Lomita Drive, Stanford, CA 94305",
    geo={"latitude": "37.432981", "longitude": "-122.170494", "street": "328 Lomita Drive",
         "city": "Stanford", "state": "CA", "zip": "94305"},
)
EXHIBITION_DAY_2 = copy.deepcopy(EXHIBITION_DAY_1)
EXHIBITION_DAY_2["event"]["event_instances"][0]["event_instance"].update(
    id=52881225063271, start="2026-11-13T00:00:00-08:00"
)

# All-day, with a published closing time, and no venue or coordinates at all.
EXHIBITION_NO_VENUE = _row(
    54470477504285,
    "California Current: Art and Histories from the Bay Area",
    "california-current-art-and-histories-from-the-bay-area-6587",
    (54470477509409, "2026-11-12T00:00:00-08:00", "2026-11-12T18:00:00-08:00", True),
    types=("Exhibition",),
    audience=("General Public",),
    recurring=True,
)

BOOK_TALK_HIDDEN_VENUE = _row(
    54162171268165,
    "Book Talk: Changing Gender",
    "book-talk-changing-gender",
    (54162171269190, "2026-11-12T12:00:00-08:00", "2026-11-12T13:00:00-08:00", False),
    types=("Lecture/Presentation/Talk",),
    location_name="RSVP for location",
    departments=[{"name": "Clayman Institute for Gender Research"}],
)

VIRTUAL_TALK = _row(
    53859860302679,
    "Open Wide the Doors: The Prison Memoirs of Mahvash Sabet",
    "open-wide-the-doors-the-prison-memoirs-of-mahvash-sabet",
    (53859860302680, "2026-11-12T10:00:00-08:00", "2026-11-12T11:00:00-08:00", False),
    types=("Lecture/Presentation/Talk",),
    audience=("Everyone",),
    experience="virtual",
    free=True,
    ticket_cost="Free and open to the public. Register for Zoom link.",
)

ACADEMIC_DATE = _row(
    53870927640204,
    "Autumn Quarter: Course withdrawal deadline (5:00 p.m.)",
    "course-withdrawal-deadline-500-pm",
    (53870927641229, "2026-11-13T00:00:00-08:00", None, True),
    types=("Academic Dates",),
    audience=("Everyone",),
)

PHD_DEFENSE = _row(
    54410800154180,
    "PhD Dissertation Defense: A. Candidate",
    "phd-dissertation-defense-a-candidate",
    (54410800155205, "2026-11-13T13:00:00-08:00", None, False),
    types=("PhD Defense",),
    audience=("Everyone",),
    location_name="Clark Center",
    geo={"latitude": "37.431462", "longitude": "-122.174561", "street": "318 Campus Drive",
         "city": "Palo Alto", "state": "CA", "zip": "94305"},
)

SUPPORT_SPACE = _row(
    54408877728302,
    "Let's Sweet Talk",
    "lets-sweet-talk",
    (54408877728303, "2026-11-12T13:30:00-08:00", "2026-11-12T15:30:00-08:00", False),
    types=("Social Event/Reception", "Support Space"),
    audience=("Students", "Students - Undergraduates", "Students - Graduates"),
    location_name="Asian American Activities Center",
    geo={"latitude": "37.424927", "longitude": "-122.170123", "street": "524 Lasuen Mall",
         "city": "Stanford", "state": "CA", "zip": "94305"},
)

INTERNAL_SEMINAR = _row(
    54444054767078,
    "Earth System Science Seminar Series",
    "earth-system-science-seminar-series",
    (54444054768103, "2026-11-12T12:00:00-08:00", "2026-11-12T13:00:00-08:00", False),
    types=("Lecture/Presentation/Talk",),
    audience=("Students", "Postdocs", "Faculty", "Staff"),
    location_name="Y2E2 Building",
    geo={"latitude": "37.42816", "longitude": "-122.175935", "street": "473 Via Ortega",
         "city": "Stanford", "state": "CA", "zip": "94305"},
)

# Filed under "Other", in person, for "Everyone", every day for months.
STUDY_RECRUITMENT = _row(
    51827589730708,
    "A CLINICAL RESEARCH STUDY PROGRAM FOR MAJOR DEPRESSIVE DISORDER (MDD)",
    "neurocrine",
    (54436057574453, "2026-11-12T00:00:00-08:00", None, True),
    types=("Other",),
    audience=("Everyone",),
    recurring=True,
    departments=[{"name": "Department of Psychiatry"}],
)

# --- SJSU (types and the audience filter are named differently) --------------

SJSU = "https://events.sjsu.edu"
SJSU_PUBLIC = ("Alumni", "SJSU Employees", "General Public", "Students")

SWEENEY_TODD = _row(
    54004133775073,
    "SJSU Theatre presents Sweeney Todd: The Demon Barber of Fleet Street",
    "sjsu-theatre-presents-sweeney-todd-the-demon-barber-of-fleet-street",
    (54004133775074, "2026-11-13T19:30:00-08:00", "2026-11-13T22:00:00-08:00", False),
    types=("Exhibitions, Performances, Installations",),
    audience=(*SJSU_PUBLIC, "Donors"),
    audience_key="event_target_audience",
    site=SJSU,
    recurring=True,
    location_name="Hammer Theater Center",
    address="101 Paseo De San Antonio, San José, CA 95113",
    ticket_cost="$28",
    geo={"latitude": "37.333717", "longitude": "-121.886459", "street": "183 South Third Street",
         "city": "San Jose", "state": "CA", "zip": "95113"},
    departments=[{"name": "Hammer Theatre"}],
)

STEINBECK_AWARD_IN_SF = _row(
    54295606722878,
    "Zoe Kazan & Florence Pugh Steinbeck Award Event",
    "zoe-kazan-florence-pugh-steinbeck-award-event",
    (54295606723903, "2026-11-12T19:30:00-08:00", None, False),
    types=("Exhibitions, Performances, Installations", "Social Events and Gatherings"),
    audience=(*SJSU_PUBLIC, "Donors"),
    audience_key="event_target_audience",
    site=SJSU,
    location_name="Sydney Goldstein Theater",
    address="275 Hayes St, San Francisco, CA 94102",
    geo={"latitude": "37.776957", "longitude": "-122.42082", "street": "275 Hayes Street",
         "city": "San Francisco", "state": "CA", "zip": "94102"},
)

HOME_GAME = _row(
    53697993263450,
    "Men's Basketball -  San Jose State vs. UC Riverside",
    "mens-basketball-san-jose-state-vs-uc-riverside",
    (53697993263451, "2026-11-12T19:00:00-08:00", "2026-11-12T21:00:00-08:00", False),
    types=("Athletics Events",),
    audience=SJSU_PUBLIC,
    audience_key="event_target_audience",
    site=SJSU,
    location_name="San Jose, Calif.",
)

AWAY_GAME = _row(
    52635928331056,
    "Women's Volleyball -  San Jose State at Nevada",
    "womens-volleyball-san-jose-state-at-nevada-3187",
    (52635928332081, "2026-11-12T18:00:00-08:00", "2026-11-12T20:00:00-08:00", False),
    types=("Athletics Events",),
    audience=SJSU_PUBLIC,
    audience_key="event_target_audience",
    site=SJSU,
    location_name="Reno, Nev.",
)

VENUE_TBA = _row(
    53609112444431,
    "Women's Soccer -  San Jose State vs. Mountain West Tournament",
    "womens-soccer-san-jose-state-vs-mountain-west-tournament",
    (53609112480282, "2026-11-12T00:00:00-08:00", None, True),
    types=("Athletics Events",),
    audience=SJSU_PUBLIC,
    audience_key="event_target_audience",
    site=SJSU,
    recurring=True,
    location_name="TBA",
)

# Student-org rows carry no event type and hide the location behind a login.
UNTYPED_STUDENT_EVENT = _row(
    54387765097312,
    "Teas & Teddies",
    "teas-teddies",
    (54387765100385, "2026-11-16T14:00:00-08:00", "2026-11-16T17:00:00-08:00", False),
    audience=("Students",),
    audience_key="event_target_audience",
    site=SJSU,
    location_name="Sign in to download the location",
)

STUDENTS_ONLY_SOCIAL = _row(
    54400000000001,
    "Global Connections: Wellness for International Students (WIS)",
    "global-connections-wis",
    (54400000000002, "2026-11-16T14:00:00-08:00", "2026-11-16T15:00:00-08:00", False),
    types=("Social Events and Gatherings",),
    audience=("Students", "Current Students"),
    audience_key="event_target_audience",
    site=SJSU,
    location_name="Student Union",
    geo={"latitude": "37.336347", "longitude": "-121.881373", "street": "211 South 9th Street",
         "city": "San Jose", "state": "CA", "zip": "95112"},
)


def _variant(row: dict[str, Any], **fields: Any) -> dict[str, Any]:
    changed = copy.deepcopy(row)
    changed["event"].update(fields)
    return changed


def _page(rows: list[dict[str, Any]], *, current: int = 1, total: int = 1) -> dict[str, Any]:
    return {
        "events": rows,
        "page": {"current": current, "size": 100, "total": total},
        "date": {"first": "2026-11-12", "last": "2026-11-26"},
    }


def _only(payloads: list[dict[str, Any]]) -> dict[str, Any]:
    assert len(payloads) == 1
    return payloads[0]


async def _fetch(
    source_cls: type[LocalistSource], rows: list[dict[str, Any]], *, today: date = TODAY
) -> tuple[LocalistSource, list[dict[str, Any]]]:
    source = source_cls()
    payloads = await source.fetch_events(payload=_page(rows), today=today)
    return source, payloads


def _paged_source(
    pages: dict[int, Any], source_cls: type[LocalistSource] = StanfordEventsSource, **overrides: Any
) -> tuple[LocalistSource, list[httpx.Request]]:
    """A source whose HTTP client serves ``pages[n]`` for ``?page=n``.

    A page value may be a payload dict, an int (HTTP status) or a str (raw body).
    """
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        body = pages.get(int(request.url.params["page"]), 404)
        if isinstance(body, int):
            return httpx.Response(body, text="error")
        if isinstance(body, str):
            return httpx.Response(200, text=body)
        return httpx.Response(200, json=body)

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    source = source_cls(client=client, max_requests_per_second=1000)
    for name, value in overrides.items():
        setattr(source, name, value)
    return source, requests


# ---------------------------------------------------------------------------
# Registry / politeness
# ---------------------------------------------------------------------------


def test_each_campus_is_its_own_registered_tier_2_source() -> None:
    assert registry.get("stanford_events") is StanfordEventsSource
    assert registry.get("sjsu_events") is SJSUEventsSource
    for source_cls in (StanfordEventsSource, SJSUEventsSource):
        assert issubclass(source_cls, LocalistSource)
        assert source_cls.source_tier == 2
        assert source_cls.default_max_requests_per_second == 1
        assert source_cls.source_name == source_cls.campus.source_id
        assert source_cls.horizon_days == 14


# ---------------------------------------------------------------------------
# Normalisation
# ---------------------------------------------------------------------------


async def test_normalises_a_typical_public_event() -> None:
    _, payloads = await _fetch(StanfordEventsSource, [BAROQUE_RECITAL])
    event = _only(payloads)

    assert event["title"] == "Stanford Baroque Recital"
    assert event["source_name"] == "stanford_events"
    assert event["source_tier"] == 2
    # The occurrence id, not the event id: one row per date.
    assert event["source_event_id"] == "54364856936678"
    assert event["external_url"] == "https://events.stanford.edu/event/stanford-baroque-recital"
    # 12:00-13:00 Pacific Standard Time, stored in UTC; a published time is not estimated.
    assert event["start_at"] == datetime(2026, 11, 12, 20, 0, tzinfo=timezone.utc)
    assert event["end_at"] == datetime(2026, 11, 12, 21, 0, tzinfo=timezone.utc)
    assert event["start_time_is_estimated"] is False
    assert event["venue_name"] == "Braun Music Center"
    assert event["raw_address"] == "541 Lasuen Mall, Stanford, CA 94305"
    assert event["city"] == "Stanford"
    assert event["location"] == "POINT(-122.169296 37.423758)"
    assert event["location_confidence"] == 0.9
    assert event["is_free"] is True
    assert event["price"] == 0.0
    assert event["currency"] == "USD"
    assert event["categories"] == ["Arts & Theatre"]
    assert event["organizer_name"] == "Department of Music"
    assert event["status"] == "scheduled"
    assert event["image_url"].startswith("https://localist-images.azureedge.net/photos/")
    # Plain text on one line.
    assert event["description"].startswith("Stanford harpsichordists, recorder players")
    assert "\n" not in event["description"]


async def test_description_is_kept_short() -> None:
    long_text = "Baroque music by Handel, Byrd and Purcell. " * 60
    _, payloads = await _fetch(
        StanfordEventsSource, [_variant(BAROQUE_RECITAL, description_text=long_text)]
    )
    description = _only(payloads)["description"]

    assert len(description) <= 600
    assert description.endswith("…")


async def test_summer_times_use_daylight_offset() -> None:
    row = copy.deepcopy(BAROQUE_RECITAL)
    row["event"]["event_instances"][0]["event_instance"].update(
        start="2026-07-01T19:00:00-07:00", end="2026-07-01T20:30:00-07:00"
    )
    _, payloads = await _fetch(StanfordEventsSource, [row], today=date(2026, 7, 1))
    event = _only(payloads)

    assert event["start_at"] == datetime(2026, 7, 2, 2, 0, tzinfo=timezone.utc)
    assert event["end_at"] == datetime(2026, 7, 2, 3, 30, tzinfo=timezone.utc)


async def test_hybrid_events_are_kept_and_unknown_price_is_not_free() -> None:
    _, payloads = await _fetch(StanfordEventsSource, [HYBRID_TALK])
    event = _only(payloads)

    assert event["title"] == "How to Fix a Broken Hierarchy"
    # ``free: false`` with no ticket cost is "not stated", not "paid".
    assert event["is_free"] is False
    assert event["price"] is None
    assert event["currency"] is None
    # Talks have no bucket of their own: Miscellaneous plus the vibe tag.
    assert event["categories"] == ["Miscellaneous"]
    assert event["tags"] == ["intellectual"]
    # No department on the row: the campus is the organizer.
    assert event["organizer_name"] == "Stanford University"


async def test_price_range_is_parsed_and_absent_audience_is_allowed() -> None:
    _, payloads = await _fetch(StanfordEventsSource, [OUR_TOWN])
    event = _only(payloads)

    assert event["title"] == "MAIN STAGE | Our Town"
    assert event["is_free"] is False
    assert event["price"] == 5.0
    assert event["currency"] == "USD"


async def test_all_day_rows_do_not_get_an_invented_clock_time() -> None:
    _, payloads = await _fetch(StanfordEventsSource, [EXHIBITION_DAY_1])
    event = _only(payloads)

    # Local midnight to 23:59, flagged: only the calendar date is published.
    assert event["start_at"] == datetime(2026, 11, 12, 8, 0, tzinfo=timezone.utc)
    assert event["end_at"] == datetime(2026, 11, 13, 7, 59, tzinfo=timezone.utc)
    assert event["start_time_is_estimated"] is True
    assert event["categories"] == ["Arts & Theatre"]


async def test_all_day_row_keeps_a_published_closing_time() -> None:
    _, payloads = await _fetch(StanfordEventsSource, [EXHIBITION_NO_VENUE])
    event = _only(payloads)

    assert event["start_time_is_estimated"] is True
    assert event["end_at"] == datetime(2026, 11, 13, 2, 0, tzinfo=timezone.utc)  # 18:00 PST


async def test_each_occurrence_is_its_own_event_with_a_stable_id() -> None:
    rows = [EXHIBITION_DAY_1, EXHIBITION_DAY_2]
    _, first = await _fetch(StanfordEventsSource, rows)
    _, second = await _fetch(StanfordEventsSource, rows)

    assert [e["source_event_id"] for e in first] == ["52881225062246", "52881225063271"]
    assert [e["start_at"].day for e in first] == [12, 13]
    assert len({e["external_url"] for e in first}) == 1
    # Re-running yields the same identities: the pipeline updates, not duplicates.
    assert [e["source_event_id"] for e in second] == [e["source_event_id"] for e in first]


async def test_the_same_occurrence_on_two_pages_is_emitted_once() -> None:
    _, payloads = await _fetch(StanfordEventsSource, [BAROQUE_RECITAL, BAROQUE_RECITAL])
    assert len(payloads) == 1


async def test_emitted_categories_and_tags_are_existing_vocabulary() -> None:
    _, stanford = await _fetch(
        StanfordEventsSource, [BAROQUE_RECITAL, HYBRID_TALK, EXHIBITION_DAY_1, OUR_TOWN]
    )
    _, sjsu = await _fetch(SJSUEventsSource, [SWEENEY_TODD, STEINBECK_AWARD_IN_SF, HOME_GAME])

    for event in (*stanford, *sjsu):
        assert event["categories"], event["title"]
        # Nothing the pipeline's taxonomy would drop.
        assert categories_v1(event["categories"]) == event["categories"]
        assert len(canonical_vibe_tags(event["tags"])) == len(event["tags"])


# ---------------------------------------------------------------------------
# Location, city, confidence
# ---------------------------------------------------------------------------


async def test_city_and_coordinates_come_from_the_feed_even_off_campus() -> None:
    _, payloads = await _fetch(SJSUEventsSource, [STEINBECK_AWARD_IN_SF, SWEENEY_TODD])
    by_title = {e["title"]: e for e in payloads}

    award = by_title["Zoe Kazan & Florence Pugh Steinbeck Award Event"]
    assert award["source_name"] == "sjsu_events"
    assert award["city"] == "San Francisco"
    assert award["raw_address"] == "275 Hayes Street, San Francisco, CA 94102"
    assert award["location"] == "POINT(-122.42082 37.776957)"
    assert award["location_confidence"] == 0.9
    assert award["categories"] == ["Arts & Theatre", "Social"]

    todd = by_title["SJSU Theatre presents Sweeney Todd: The Demon Barber of Fleet Street"]
    assert todd["city"] == "San Jose"
    assert todd["price"] == 28.0
    assert todd["is_free"] is False
    assert todd["organizer_name"] == "Hammer Theatre"


async def test_hidden_venue_falls_back_to_the_campus_centroid_at_low_confidence() -> None:
    _, payloads = await _fetch(StanfordEventsSource, [BOOK_TALK_HIDDEN_VENUE])
    event = _only(payloads)

    # "RSVP for location" names no place.
    assert event["venue_name"] is None
    assert event["city"] == "Stanford"
    # City in postal form: this is what places a low-confidence row downstream.
    assert event["raw_address"] == "Stanford, CA"
    assert event["location"] == "POINT(-122.1697 37.4275)"
    assert event["location_confidence"] <= 0.4


async def test_home_game_listed_by_city_gets_the_campus_centroid_not_a_venue() -> None:
    _, payloads = await _fetch(SJSUEventsSource, [HOME_GAME])
    event = _only(payloads)

    assert event["venue_name"] is None  # "San Jose, Calif." is a city, not a venue
    assert event["city"] == "San Jose"
    assert event["raw_address"] == "San Jose, CA"
    assert event["location"] == "POINT(-121.8811 37.3352)"
    assert event["location_confidence"] <= 0.4
    assert event["categories"] == ["Sports"]


async def test_in_state_city_uses_that_citys_centroid_and_unknown_cities_are_dropped() -> None:
    oakland = _variant(HOME_GAME, location_name="Oakland, Calif.")
    unknown = _variant(HOME_GAME, location_name="San Luis Obispo, Calif.")
    unknown["event"]["event_instances"][0]["event_instance"]["id"] = 1

    source, payloads = await _fetch(SJSUEventsSource, [oakland, unknown])
    event = _only(payloads)

    assert event["city"] == "Oakland"
    assert event["location"] == "POINT(-122.2712 37.8044)"
    assert event["location_confidence"] <= 0.4
    assert source.last_filter_counts == {"no_usable_location": 1}


async def test_a_comma_in_a_room_name_is_not_mistaken_for_a_city() -> None:
    row = _variant(BOOK_TALK_HIDDEN_VENUE, location_name="Old Union, Clubhouse")
    _, payloads = await _fetch(StanfordEventsSource, [row])
    event = _only(payloads)

    assert event["venue_name"] == "Old Union, Clubhouse"
    assert event["city"] == "Stanford"


async def test_venue_cache_hit_far_from_campus_is_a_name_collision_not_a_location() -> None:
    # "Mezzanine" is a San Francisco club in the venue cache.
    row = _variant(BOOK_TALK_HIDDEN_VENUE, location_name="Mezzanine")
    _, payloads = await _fetch(StanfordEventsSource, [row])
    event = _only(payloads)

    assert event["venue_name"] == "Mezzanine"
    assert event["location"] == "POINT(-122.1697 37.4275)"
    assert event["location_confidence"] <= 0.4


async def test_known_venue_near_campus_is_used_when_the_feed_has_no_coordinates() -> None:
    row = _variant(HOME_GAME, location_name="SAP Center")
    _, payloads = await _fetch(SJSUEventsSource, [row])
    event = _only(payloads)

    assert event["venue_name"] == "SAP Center"
    assert event["location"] == "POINT(-121.901 37.3327)"
    assert event["location_confidence"] == 0.9


async def test_the_cache_entry_for_the_campus_itself_stays_low_confidence() -> None:
    row = _variant(BOOK_TALK_HIDDEN_VENUE, location_name="Stanford University")
    _, payloads = await _fetch(StanfordEventsSource, [row])

    assert _only(payloads)["location_confidence"] <= 0.4


# ---------------------------------------------------------------------------
# Public-interest filter
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("source_cls", "row", "reason"),
    [
        (StanfordEventsSource, VIRTUAL_TALK, "virtual"),
        (StanfordEventsSource, _variant(BAROQUE_RECITAL, private=True), "private"),
        (StanfordEventsSource, _variant(BAROQUE_RECITAL, status="canceled"), "not_live"),
        (StanfordEventsSource, ACADEMIC_DATE, "blocked_type"),
        (StanfordEventsSource, PHD_DEFENSE, "blocked_type"),
        # A blocked type wins over an allowlisted one on the same row.
        (StanfordEventsSource, SUPPORT_SPACE, "blocked_type"),
        (
            StanfordEventsSource,
            _row(1, "Navigating your Career", "navigating-your-career",
                 (2, "2026-11-12T08:00:00-08:00", None, False), types=("Meeting",)),
            "blocked_type",
        ),
        (StanfordEventsSource, STUDY_RECRUITMENT, "type_not_allowlisted"),
        (
            StanfordEventsSource,
            _row(3, "SDRC Friday Seminar 11/13/26", "sdrc-friday-seminar",
                 (4, "2026-11-13T12:00:00-08:00", None, False), types=("Class/Seminar",)),
            "type_not_allowlisted",
        ),
        (StanfordEventsSource, INTERNAL_SEMINAR, "audience_not_public"),
        (SJSUEventsSource, UNTYPED_STUDENT_EVENT, "type_not_allowlisted"),
        (SJSUEventsSource, STUDENTS_ONLY_SOCIAL, "audience_not_public"),
        (SJSUEventsSource, AWAY_GAME, "no_usable_location"),
        (SJSUEventsSource, VENUE_TBA, "no_usable_location"),
    ],
)
async def test_each_exclusion_rule(
    source_cls: type[LocalistSource], row: dict[str, Any], reason: str
) -> None:
    source, payloads = await _fetch(source_cls, [row])

    assert payloads == []
    assert source.exclusion_reason(row["event"]) == reason
    assert source.last_filter_counts == {reason: 1}


async def test_study_recruitment_is_excluded_even_when_typed_as_a_public_talk() -> None:
    row = _variant(STUDY_RECRUITMENT)
    row["event"]["filters"]["event_types"] = [{"name": "Lecture/Presentation/Talk"}]

    source, payloads = await _fetch(StanfordEventsSource, [row])

    assert payloads == []
    assert source.last_filter_counts == {"study_recruitment": 1}


async def test_only_public_in_person_rows_survive_a_mixed_page() -> None:
    rows = [
        STUDY_RECRUITMENT, EXHIBITION_DAY_1, VIRTUAL_TALK, BAROQUE_RECITAL, INTERNAL_SEMINAR,
        SUPPORT_SPACE, ACADEMIC_DATE, PHD_DEFENSE, OUR_TOWN, HYBRID_TALK,
    ]
    source, payloads = await _fetch(StanfordEventsSource, rows)

    assert [e["title"] for e in payloads] == [
        "Carolyn Lazard: Long Take",
        "Stanford Baroque Recital",
        "MAIN STAGE | Our Town",
        "How to Fix a Broken Hierarchy",
    ]
    assert source.last_filter_counts == {
        "type_not_allowlisted": 1, "virtual": 1, "audience_not_public": 1, "blocked_type": 3,
    }
    assert source.last_fetch_error is None


async def test_an_occurrence_outside_the_horizon_is_dropped() -> None:
    row = copy.deepcopy(BAROQUE_RECITAL)
    row["event"]["event_instances"][0]["event_instance"]["start"] = "2026-12-20T12:00:00-08:00"

    source, payloads = await _fetch(StanfordEventsSource, [row])

    assert payloads == []
    assert source.last_filter_counts == {"outside_horizon": 1}


async def test_a_page_with_nothing_public_explains_itself() -> None:
    source, payloads = await _fetch(StanfordEventsSource, [VIRTUAL_TALK, ACADEMIC_DATE])

    assert payloads == []
    assert source.last_fetch_error is None
    assert "2 calendar rows" in source.last_empty_reason
    assert "virtual=1" in source.last_empty_reason
    assert "blocked_type=1" in source.last_empty_reason


# ---------------------------------------------------------------------------
# Crawl: pagination, caps, partial failures
# ---------------------------------------------------------------------------


async def test_follows_pages_to_the_feeds_own_total_with_an_honest_user_agent() -> None:
    source, requests = _paged_source(
        {
            1: _page([BAROQUE_RECITAL], current=1, total=3),
            2: _page([OUR_TOWN, VIRTUAL_TALK], current=2, total=3),
            3: _page([HYBRID_TALK], current=3, total=3),
        }
    )

    payloads = await source.fetch_events(today=TODAY)

    assert [str(r.url) for r in requests] == [
        f"{STANFORD_API}?days=14&pp=100&page={n}" for n in (1, 2, 3)
    ]
    assert all(r.headers["user-agent"] == USER_AGENT for r in requests)
    assert "truth-of-fun" in USER_AGENT and "Mozilla" not in USER_AGENT
    assert [e["title"] for e in payloads] == [
        "Stanford Baroque Recital", "MAIN STAGE | Our Town", "How to Fix a Broken Hierarchy",
    ]
    assert source.requests_made == 3
    assert source.last_fetch_error is None


async def test_each_campus_calls_its_own_calendar() -> None:
    source, requests = _paged_source({1: _page([SWEENEY_TODD])}, SJSUEventsSource)

    payloads = await source.fetch_events(today=TODAY)

    assert [str(r.url) for r in requests] == [
        "https://events.sjsu.edu/api/2/events?days=14&pp=100&page=1"
    ]
    assert _only(payloads)["source_name"] == "sjsu_events"


async def test_request_cap_stops_the_crawl_and_reports_it_incomplete() -> None:
    pages = {n: _page([BAROQUE_RECITAL], current=n, total=20) for n in range(1, 21)}
    source, requests = _paged_source(pages, max_pages=2)

    payloads = await source.fetch_events(today=TODAY)

    assert len(requests) == 2
    assert len(payloads) == 1
    assert "cap" in source.last_fetch_error.lower()


async def test_event_cap_bounds_the_run_and_reports_it_incomplete() -> None:
    source = StanfordEventsSource()
    source.max_events = 1

    payloads = await source.fetch_events(payload=_page([BAROQUE_RECITAL, OUR_TOWN]), today=TODAY)

    assert [e["title"] for e in payloads] == ["Stanford Baroque Recital"]
    assert "Event cap reached" in source.last_fetch_error


async def test_a_failed_later_page_keeps_earlier_events_and_reports_a_partial_fetch() -> None:
    source, requests = _paged_source({1: _page([BAROQUE_RECITAL], current=1, total=3), 2: 404})

    payloads = await source.fetch_events(today=TODAY)

    assert len(requests) == 2
    assert [e["title"] for e in payloads] == ["Stanford Baroque Recital"]
    assert "HTTPStatusError" in source.last_fetch_error


async def test_a_garbled_later_page_is_a_partial_fetch_too() -> None:
    source, _ = _paged_source(
        {1: _page([BAROQUE_RECITAL], current=1, total=2), 2: "<html>maintenance</html>"}
    )

    payloads = await source.fetch_events(today=TODAY)

    assert len(payloads) == 1
    assert "not valid JSON" in source.last_fetch_error


async def test_a_failed_first_page_raises_so_the_worker_marks_the_source_failing() -> None:
    source, _ = _paged_source({1: 404})

    with pytest.raises(httpx.HTTPStatusError):
        await source.fetch_events(today=TODAY)


async def test_missing_pagination_metadata_is_reported_not_assumed_complete() -> None:
    source, requests = _paged_source({1: {"events": [BAROQUE_RECITAL]}})

    payloads = await source.fetch_events(today=TODAY)

    assert len(requests) == 1
    assert len(payloads) == 1
    assert "Pagination metadata missing" in source.last_fetch_error


def _exhibition_days(count: int) -> list[dict]:
    rows = []
    for offset in range(count):
        row = copy.deepcopy(EXHIBITION_DAY_1)
        row["event"]["event_instances"][0]["event_instance"].update(
            id=52881225062246 + offset, start=f"2026-11-{12 + offset:02d}T00:00:00-08:00"
        )
        rows.append(row)
    return rows


async def test_long_running_exhibition_is_one_ongoing_row_not_one_per_day() -> None:
    source, payloads = await _fetch(StanfordEventsSource, _exhibition_days(6))
    event = _only(payloads)

    # Starts on the first listed day and runs through the last one.
    assert event["start_at"] == datetime(2026, 11, 12, 8, 0, tzinfo=timezone.utc)
    assert event["end_at"] == datetime(2026, 11, 18, 7, 59, tzinfo=timezone.utc)
    assert event["start_time_is_estimated"] is True
    # Event-level identity: tomorrow's crawl (whose first day is the 13th)
    # updates this row instead of adding another.
    assert event["source_event_id"] == "52881224936195:ongoing"
    assert source.last_filter_counts["ongoing_days_collapsed"] == 5

    _, tomorrow = await _fetch(StanfordEventsSource, _exhibition_days(6)[1:])
    assert _only(tomorrow)["source_event_id"] == event["source_event_id"]


async def test_short_all_day_runs_keep_one_row_per_day() -> None:
    _, payloads = await _fetch(StanfordEventsSource, _exhibition_days(3))
    assert len(payloads) == 3
    assert all(":ongoing" not in e["source_event_id"] for e in payloads)
