"""BiblioCommons connector (Oakland and San José public libraries).

Events, locations, types and audiences below are trimmed from the live gateway
(``https://gateway.bibliocommons.com/v2/libraries/oaklandlibrary/events/search``
and ``.../libraries/sjpl/events/search``), captured 2026-11-12: unused keys
dropped, descriptions shortened, and the staff ``contact`` block (name, email,
phone) removed entirely. Rows marked "variant" change one field of a real row
to isolate a rule. Nothing touches the network; paged crawls are served
through ``httpx.MockTransport``.
"""

from __future__ import annotations

import copy
from datetime import date, datetime, timezone
from typing import Any

import httpx
import pytest

from app.ingestion import registry
from app.ingestion.sources._calendar_common import USER_AGENT
from app.ingestion.sources.bibliocommons import BiblioCommonsSource
from app.ingestion.sources.bibliocommons import OaklandLibrarySource
from app.ingestion.sources.bibliocommons import SanJoseLibrarySource
from app.services.catalog_taxonomy_v1 import categories_v1, legacy_genres_v1
from app.services.tags import canonical_vibe_tags

pytestmark = pytest.mark.anyio

TODAY = date(2026, 11, 12)
OAKLAND_SEARCH = "https://gateway.bibliocommons.com/v2/libraries/oaklandlibrary/events/search"

# --- Entities (Oakland) -------------------------------------------------------

AUDIENCES = {
    "aud-adults": "Adults", "aud-families": "Families", "aud-kids": "Kids", "aud-teens": "Teens",
    "aud-seniors": "Seniors", "aud-toddlers": "Toddlers", "aud-babies": "Babies",
    # San José spells its audiences with ages.
    "sj-kids": "Kids, ages 5-10", "sj-teens": "Teens, ages 12-18", "sj-adults": "Adults, ages 18+",
}
TYPES = {
    "type-fitness": "Fitness", "type-wellness": "Health and Wellness", "type-outdoor": "Outdoor",
    "type-author": "Meet the Author", "type-history": "Oakland History Center", "type-talks": "Talks",
    "type-storytime": "Storytime", "type-aamlo": "AAMLO Event", "type-film": "Film Screening ",
    "type-tech": "Computers & Technology", "type-tech-support": "Computer & Technology Support",
    "type-health-services": "Health Services", "type-support-services": "Support Services",
    "type-community": "Community Event", "type-discussion": "Discussion Circle",
    "sj-steam": "STEAM", "sj-celebrations": "Celebrations & Festivities",
}


def _location(location_id: str, name: str, number: str, street: str, city: str, zip_code: str,
              lat: float, lng: float, state: str = "California") -> dict[str, Any]:
    return {
        "id": location_id,
        "name": name,
        "address": {"country": "US", "zip": zip_code, "state": state, "city": city,
                    "street": street, "number": number},
        "mapLocation": {"centrePoint": {"lng": lng, "lat": lat}, "timeZone": "America/Los_Angeles"},
    }


LOCATIONS = {
    "PMA": _location("PMA", "Piedmont Avenue Branch", "80", "Echo Avenue", "Oakland", "94611",
                     37.82784350000001, -122.2481511),
    "XXA": _location("XXA", "Main Library", "125", "14th Street", "Oakland", "94612",
                     37.80094379066671, -122.26367525522537),
    "MOA": _location("MOA", "Montclair Branch", "1687", "Mountain Boulevard", "Oakland", "94611",
                     37.8319831, -122.2141107),
    "ELA": _location("ELA", "Elmhurst Branch", "1427", "88th Avenue", "Oakland", "94621",
                     37.7515, -122.1746),
    # San José
    "09": _location("09", "Berryessa", "3355", "Noble Avenue", "San Jose", "95132",
                    37.3939433, -121.84073769999998, state="CA"),
    "21": _location("21", "Vineland", "1450", "Blossom Hill Rd", "San Jose", "95118",
                    37.2401849, -121.89248800000001, state="CA"),
    # The gateway's placeholder for online programmes: no address, no point.
    "BC_VIRTUAL": {"id": "BC_VIRTUAL", "name": "Online events", "address": {},
                   "mapLocation": {"utcOffsetNow": None}},
}
PLACES = {
    "6abc33cbe06996003a801fe8": _location(
        "6abc33cbe06996003a801fe8", "Grand Lake Farmers Market", "746", "Grand Avenue", "Oakland",
        "94610", 37.8110512, -122.2486136, state="CA"),
}
IMAGES = {
    "img-yoga": {"id": "img-yoga", "url": "https://oaklandlibrary.bibliocommons.com/events/uploads/images/full/786deb4ff625f28f75b960a9b716bdab/Chairyoga(890x445px).png"},
}


def _event(
    event_id: str,
    title: str,
    start: str,
    end: str | None,
    *,
    branch: str | None = None,
    place: str | None = None,
    types: tuple[str, ...] = (),
    audiences: tuple[str, ...] = (),
    recurring: bool = False,
    cancelled: bool = False,
    description: str = "",
    image: str | None = None,
) -> dict[str, Any]:
    return {
        "id": event_id,
        "seriesId": f"series-{event_id}",
        "isRecurring": recurring,
        "definition": {
            "start": start,
            "end": end,
            "title": title,
            "description": description,
            "branchLocationId": branch,
            "nonBranchLocationId": place,
            "audienceIds": list(audiences),
            "typeIds": list(types),
            "featuredImageId": image,
            "isCancelled": cancelled,
        },
    }


CHAIR_YOGA = _event(
    "6a91e1171c197d11325b855e", "Chair Yoga ", "2026-11-12T10:30", "2026-11-12T11:30",
    branch="PMA", types=("type-fitness", "type-wellness"), audiences=("aud-adults",),
    image="img-yoga",
    description=(
        "<p>Chair yoga is designed for those who have difficulty getting up and down from the "
        "floor due to arthritis, knee injury, back pain or any other reason.&nbsp;</p>\n"
        "<p>Learn from a certified yoga instructor how a daily practice will improve your "
        "strength.</p>"
    ),
)
DIWALI = _event(
    "6a1a1676a99bdd027d434965", "Diwali Celebration", "2026-11-12T14:30", "2026-11-12T16:30",
    branch="PMA", types=("type-outdoor",),
    audiences=("aud-adults", "aud-families", "aud-kids", "aud-teens"),
    description="<p>Celebrate Diwali at the Piedmont Ave Branch with free henna designs and diya&nbsp;lamp-making crafts!<br></p>",
)
MEET_THE_AUTHOR = _event(
    "6a3c164f48c98c3600a20b8e",
    "Meet the Author: David D. Schmidt - San Francisco Bay Area: An Environmental History",
    "2026-11-12T18:00", "2026-11-12T19:30",
    branch="XXA", types=("type-author", "type-history", "type-talks"),
    audiences=("aud-adults", "aud-seniors"),
)
FARMERS_MARKET_STORYTIME = _event(
    "6ac42dfca85a2c00337d7363", "Storytime at the Farmers Market",
    "2026-11-14T10:00", "2026-11-14T12:00",
    place="6abc33cbe06996003a801fe8", types=("type-storytime",),
    audiences=("aud-babies", "aud-families", "aud-kids", "aud-toddlers"),
)
FILM_SCREENING = _event(
    "6a82fc0fd4b10d003006fbb9", "Ghost in the Machine: Film screening and panel discussion",
    "2026-11-14T14:00", "2026-11-14T17:00",
    branch="XXA", types=("type-tech", "type-film", "type-talks"),
    audiences=("aud-adults", "aud-teens"),
)
DOLL_SHOW = _event(
    "6aa9970a6074830038271b5f", "Festival of Black Doll Show", "2026-11-14T10:00", "2026-11-14T17:00",
    branch="XXA", types=("type-aamlo",), audiences=("aud-adults", "aud-seniors"),
)
CAREGIVERS_CIRCLE = _event(
    "6ac0344e9abb62002c6bdeb9", "When You’re the One Everyone Counts On",
    "2026-11-17T17:30", "2026-11-17T19:30",
    branch="ELA",
    types=("type-community", "type-discussion", "type-health-services", "type-support-services"),
    audiences=("aud-adults", "aud-seniors"),
)
WEEKLY_STORYTIME = _event(
    "692f34cdd8681b290041f212", "Toddler Storytime", "2026-11-12T10:15", "2026-11-12T11:15",
    branch="MOA", types=("type-storytime",), audiences=("aud-toddlers",), recurring=True,
)
CANCELLED_HELP = _event(
    "68a3f20a41789673e1f22880", "Drop-In Computer Help", "2026-11-17T17:30", "2026-11-17T19:00",
    branch="XXA", types=("type-tech", "type-tech-support"), cancelled=True,
)
# variant: a one-off session tagged only with service types.
SERVICE_ONLY = _event(
    "service-only-1", "Benefits Enrollment Help", "2026-11-17T13:00", "2026-11-17T15:00",
    branch="XXA", types=("type-health-services", "type-support-services"),
)
# variant: a one-off programme filed under the gateway's online pseudo-branch.
ONLINE_BRANCH_TALK = _event(
    "online-1", "Author Talk (Online)", "2026-11-13T18:00", "2026-11-13T19:00",
    branch="BC_VIRTUAL", types=("type-talks",),
)

# --- San José --------------------------------------------------------------------

GUINEA_PIGS = _event(
    "6ae3d5dcf9d28050ccafc99d", "STEM: Guinea Pigs: History and Biology",
    "2026-11-12T13:30", "2026-11-12T15:00",
    branch="09", types=("sj-steam",), audiences=("sj-kids",),
)
# Online programmes are flagged ``isVirtual`` and carry no location id at all.
VIRTUAL_INFO_SESSION = _event(
    "6ae0f464035faf0033df697c", "Free and Affordable Courses at San Jose City College",
    "2026-11-18T12:30", "2026-11-18T13:30", audiences=("sj-adults",),
)
VIRTUAL_INFO_SESSION["definition"]["isVirtual"] = True
# Real row is recurring; variant: one-off, to exercise the date-only (all-day) shape.
GRATITUDE_TREE_ALL_DAY = _event(
    "6ad12644fee2d21deb238868", "Gratitude Tree", "2026-11-12", "2026-11-12",
    branch="21", types=("sj-celebrations",), audiences=("sj-adults", "sj-kids", "sj-teens"),
)


def _page(
    events: list[dict[str, Any]],
    *,
    page: int = 1,
    pages: int = 1,
    count: int | None = None,
    limit: int = 50,
) -> dict[str, Any]:
    """A search response in the live shape: ids in ``events.results``, rows in ``entities``."""
    return {
        "events": {
            "results": [event["id"] for event in events],
            "pagination": {
                "count": len(events) if count is None else count,
                "page": page,
                "pages": pages,
                "limit": limit,
            },
        },
        "entities": {
            "events": {event["id"]: event for event in events},
            "eventAudiences": {key: {"id": key, "name": name} for key, name in AUDIENCES.items()},
            "eventTypes": {key: {"id": key, "name": name} for key, name in TYPES.items()},
            "locations": LOCATIONS,
            "places": PLACES,
            "images": IMAGES,
        },
    }


def _only(payloads: list[dict[str, Any]]) -> dict[str, Any]:
    assert len(payloads) == 1
    return payloads[0]


async def _fetch(
    source_cls: type[BiblioCommonsSource],
    events: list[dict[str, Any]],
    *,
    today: date = TODAY,
    **overrides: Any,
) -> tuple[BiblioCommonsSource, list[dict[str, Any]]]:
    source = source_cls()
    for name, value in overrides.items():
        setattr(source, name, value)
    payloads = await source.fetch_events(payload=_page(events), today=today)
    return source, payloads


def _paged_source(
    pages: dict[int, Any],
    source_cls: type[BiblioCommonsSource] = OaklandLibrarySource,
    **overrides: Any,
) -> tuple[BiblioCommonsSource, list[httpx.Request]]:
    """A source whose client serves ``pages[n]`` for ``?page=n`` (dict, status int, or raw str)."""
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
# Registry / defaults
# ---------------------------------------------------------------------------


def test_each_library_is_its_own_registered_tier_2_source() -> None:
    assert registry.get("oakland_library") is OaklandLibrarySource
    assert registry.get("san_jose_library") is SanJoseLibrarySource
    for source_cls in (OaklandLibrarySource, SanJoseLibrarySource):
        assert issubclass(source_cls, BiblioCommonsSource)
        assert source_cls.source_tier == 2
        assert source_cls.default_max_requests_per_second == 1
        assert source_cls.source_name == source_cls.library.source_id
        assert source_cls.horizon_days == 14
        # Weekly storytimes would flood the feed: off unless asked for.
        assert source_cls.include_recurring is False
        # The gateway returns at most 50 rows whatever ``limit`` says.
        assert source_cls.page_size <= 50
        assert source_cls.max_events <= 200


# ---------------------------------------------------------------------------
# Normalisation
# ---------------------------------------------------------------------------


async def test_normalises_a_typical_library_event() -> None:
    _, payloads = await _fetch(OaklandLibrarySource, [CHAIR_YOGA])
    event = _only(payloads)

    assert event["title"] == "Chair Yoga"
    assert event["source_name"] == "oakland_library"
    assert event["source_tier"] == 2
    assert event["source_event_id"] == "6a91e1171c197d11325b855e"
    assert (
        event["external_url"]
        == "https://oaklandlibrary.bibliocommons.com/v2/events/6a91e1171c197d11325b855e"
    )
    # 10:30-11:30 Pacific wall clock (PST, UTC-8), stored in UTC, not estimated.
    assert event["start_at"] == datetime(2026, 11, 12, 18, 30, tzinfo=timezone.utc)
    assert event["end_at"] == datetime(2026, 11, 12, 19, 30, tzinfo=timezone.utc)
    assert event["start_time_is_estimated"] is False
    assert event["venue_name"] == "Oakland Public Library - Piedmont Avenue Branch"
    # Postal form, city included: the address places the event downstream.
    assert event["raw_address"] == "80 Echo Avenue, Oakland, CA 94611"
    assert event["city"] == "Oakland"
    assert event["location"] == "POINT(-122.2481511 37.82784350000001)"
    assert event["location_confidence"] == 0.9
    assert event["organizer_name"] == "Oakland Public Library"
    assert event["status"] == "scheduled"
    assert event["categories"] == ["Fitness", "Wellness"]
    assert event["image_url"].endswith("Chairyoga(890x445px).png")
    # HTML stripped, entities decoded, one line.
    assert event["description"].startswith("Chair yoga is designed for those who have difficulty")
    assert "<" not in event["description"] and "&nbsp;" not in event["description"]
    assert "\n" not in event["description"]


async def test_library_events_are_free() -> None:
    _, payloads = await _fetch(
        OaklandLibrarySource, [CHAIR_YOGA, MEET_THE_AUTHOR, FARMERS_MARKET_STORYTIME]
    )

    assert len(payloads) == 3
    for event in payloads:
        assert event["is_free"] is True
        assert event["price"] == 0.0
        assert event["currency"] == "USD"


async def test_description_is_kept_short() -> None:
    long_event = copy.deepcopy(CHAIR_YOGA)
    long_event["definition"]["description"] = "<p>" + "Stretch, breathe and balance. " * 80 + "</p>"

    _, payloads = await _fetch(OaklandLibrarySource, [long_event])
    description = _only(payloads)["description"]

    assert len(description) <= 600
    assert description.endswith("…")


async def test_summer_times_use_daylight_offset() -> None:
    summer = copy.deepcopy(CHAIR_YOGA)
    summer["definition"].update(start="2026-07-01T18:00", end="2026-07-01T19:30")

    _, payloads = await _fetch(OaklandLibrarySource, [summer], today=date(2026, 7, 1))
    event = _only(payloads)

    assert event["start_at"] == datetime(2026, 7, 2, 1, 0, tzinfo=timezone.utc)  # PDT, UTC-7
    assert event["end_at"] == datetime(2026, 7, 2, 2, 30, tzinfo=timezone.utc)


async def test_date_only_events_are_all_day_without_an_invented_clock_time() -> None:
    _, payloads = await _fetch(SanJoseLibrarySource, [GRATITUDE_TREE_ALL_DAY])
    event = _only(payloads)

    assert event["source_name"] == "san_jose_library"
    # Local midnight to 23:59 on the published date, flagged as having no real time.
    assert event["start_at"] == datetime(2026, 11, 12, 8, 0, tzinfo=timezone.utc)
    assert event["end_at"] == datetime(2026, 11, 13, 7, 59, tzinfo=timezone.utc)
    assert event["start_time_is_estimated"] is True


async def test_ids_are_stable_across_runs_and_unique_per_occurrence() -> None:
    events = [CHAIR_YOGA, DIWALI, MEET_THE_AUTHOR]
    _, first = await _fetch(OaklandLibrarySource, events)
    _, second = await _fetch(OaklandLibrarySource, events)

    ids = [e["source_event_id"] for e in first]
    assert ids == [e["id"] for e in events]
    assert len(set(ids)) == 3
    assert [e["source_event_id"] for e in second] == ids
    assert [e["external_url"] for e in second] == [e["external_url"] for e in first]


async def test_an_event_listed_twice_is_emitted_once() -> None:
    source = OaklandLibrarySource()
    page = _page([CHAIR_YOGA])
    page["events"]["results"] = [CHAIR_YOGA["id"], CHAIR_YOGA["id"]]

    payloads = await source.fetch_events(payload=page, today=TODAY)

    assert len(payloads) == 1


# ---------------------------------------------------------------------------
# Location, city, confidence
# ---------------------------------------------------------------------------


async def test_off_site_place_uses_its_own_name_address_and_coordinates() -> None:
    _, payloads = await _fetch(OaklandLibrarySource, [FARMERS_MARKET_STORYTIME])
    event = _only(payloads)

    # Not prefixed with the library's name: it is not a branch.
    assert event["venue_name"] == "Grand Lake Farmers Market"
    assert event["raw_address"] == "746 Grand Avenue, Oakland, CA 94610"
    assert event["location"] == "POINT(-122.2486136 37.8110512)"
    assert event["location_confidence"] == 0.9


async def test_san_jose_events_carry_their_own_city_and_branch() -> None:
    _, payloads = await _fetch(SanJoseLibrarySource, [GUINEA_PIGS])
    event = _only(payloads)

    assert event["city"] == "San Jose"
    assert event["venue_name"] == "San José Public Library - Berryessa"
    assert event["raw_address"] == "3355 Noble Avenue, San Jose, CA 95132"
    assert event["external_url"] == "https://sjpl.bibliocommons.com/v2/events/6ae3d5dcf9d28050ccafc99d"
    assert event["organizer_name"] == "San José Public Library"
    assert event["location_confidence"] == 0.9


async def test_branch_without_coordinates_falls_back_to_the_city_centroid_at_low_confidence() -> None:
    page = _page([CHAIR_YOGA])
    page["entities"] = copy.deepcopy(page["entities"])
    page["entities"]["locations"]["PMA"]["mapLocation"] = {"timeZone": "America/Los_Angeles"}

    payloads = await OaklandLibrarySource().fetch_events(payload=page, today=TODAY)
    event = _only(payloads)

    assert event["city"] == "Oakland"
    assert event["raw_address"] == "80 Echo Avenue, Oakland, CA 94611"
    assert event["location"] == "POINT(-122.2712 37.8044)"  # Oakland centroid
    assert event["location_confidence"] <= 0.4


async def test_event_with_no_location_entity_gets_the_library_city_at_low_confidence() -> None:
    orphan = copy.deepcopy(CHAIR_YOGA)
    orphan["definition"]["branchLocationId"] = None

    _, payloads = await _fetch(OaklandLibrarySource, [orphan])
    event = _only(payloads)

    assert event["venue_name"] is None
    assert event["city"] == "Oakland"
    assert event["raw_address"] == "Oakland, CA"
    assert event["location_confidence"] <= 0.4


# ---------------------------------------------------------------------------
# Categories: existing vocabulary only; kids/family programming findable
# ---------------------------------------------------------------------------


async def test_types_map_onto_canonical_categories() -> None:
    _, payloads = await _fetch(
        OaklandLibrarySource, [MEET_THE_AUTHOR, FILM_SCREENING, DOLL_SHOW, CAREGIVERS_CIRCLE]
    )
    by_title = {e["title"]: e for e in payloads}

    author = by_title[MEET_THE_AUTHOR["definition"]["title"]]
    assert author["categories"] == ["Miscellaneous"]
    assert author["tags"] == ["intellectual"]
    film = by_title["Ghost in the Machine: Film screening and panel discussion"]
    assert film["categories"] == ["Film"]
    assert "film" in film["tags"]
    # A type with no specific bucket is a community gathering.
    assert by_title["Festival of Black Doll Show"]["categories"] == ["Social"]
    # Tagged with service types *and* event types: kept.
    assert "When You’re the One Everyone Counts On" in by_title


async def test_kids_and_family_programming_is_findable_through_existing_vocabulary() -> None:
    _, oakland = await _fetch(OaklandLibrarySource, [DIWALI, FARMERS_MARKET_STORYTIME, CHAIR_YOGA])
    _, san_jose = await _fetch(SanJoseLibrarySource, [GUINEA_PIGS])
    by_title = {e["title"]: e for e in (*oakland, *san_jose)}

    for title in ("Diwali Celebration", "Storytime at the Farmers Market",
                  "STEM: Guinea Pigs: History and Biology"):
        event = by_title[title]
        # The vibe the product filters on ("Family Friendly") ...
        assert "#familyfriendly" in canonical_vibe_tags(event["tags"]), title
        # ... the "Family" genre the pipeline keeps ...
        assert legacy_genres_v1(event["categories"]) == ["Family"], title
        # ... and a canonical category that survives the taxonomy.
        assert categories_v1(event["categories"]), title

    assert categories_v1(by_title["Storytime at the Farmers Market"]["categories"]) == ["Social"]
    assert categories_v1(by_title["Diwali Celebration"]["categories"]) == ["Outdoors"]
    # An adults-only class is not family programming.
    yoga = by_title["Chair Yoga"]
    assert "familyfriendly" not in yoga["tags"]
    assert "Family" not in yoga["categories"]


async def test_everything_emitted_besides_the_family_label_is_canonical() -> None:
    events = [CHAIR_YOGA, DIWALI, MEET_THE_AUTHOR, FARMERS_MARKET_STORYTIME, FILM_SCREENING,
              DOLL_SHOW, CAREGIVERS_CIRCLE]
    _, payloads = await _fetch(OaklandLibrarySource, events)

    assert len(payloads) == len(events)
    for event in payloads:
        emitted = [c for c in event["categories"] if c != "Family"]
        assert emitted and categories_v1(emitted) == emitted
        assert len(canonical_vibe_tags(event["tags"])) == len(event["tags"])


# ---------------------------------------------------------------------------
# Filter
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("event", "reason"),
    [
        (WEEKLY_STORYTIME, "recurring"),
        (CANCELLED_HELP, "cancelled"),
        (VIRTUAL_INFO_SESSION, "virtual"),
        (ONLINE_BRANCH_TALK, "virtual"),
        (SERVICE_ONLY, "service_not_event"),
        (_event("far-1", "New Year Craft", "2026-12-31T14:00", "2026-12-31T15:00", branch="XXA"),
         "outside_horizon"),
        (_event("undated-1", "Mystery Programme", "", None, branch="XXA"), "undated"),
    ],
)
async def test_each_exclusion_rule(event: dict[str, Any], reason: str) -> None:
    source, payloads = await _fetch(OaklandLibrarySource, [event])

    assert payloads == []
    assert source.last_filter_counts == {reason: 1}


async def test_recurring_events_are_ingested_only_when_asked_for() -> None:
    _, default = await _fetch(OaklandLibrarySource, [WEEKLY_STORYTIME, CHAIR_YOGA])
    _, opted_in = await _fetch(
        OaklandLibrarySource, [WEEKLY_STORYTIME, CHAIR_YOGA], include_recurring=True
    )

    assert [e["title"] for e in default] == ["Chair Yoga"]
    assert [e["title"] for e in opted_in] == ["Toddler Storytime", "Chair Yoga"]
    assert opted_in[0]["venue_name"] == "Oakland Public Library - Montclair Branch"


async def test_a_cancelled_one_off_is_not_ingested() -> None:
    cancelled = copy.deepcopy(CHAIR_YOGA)
    cancelled["definition"]["isCancelled"] = True

    source, payloads = await _fetch(OaklandLibrarySource, [cancelled, DIWALI])

    assert [e["title"] for e in payloads] == ["Diwali Celebration"]
    assert source.last_filter_counts == {"cancelled": 1}


async def test_a_page_of_only_recurring_rows_explains_the_empty_result() -> None:
    source, payloads = await _fetch(OaklandLibrarySource, [WEEKLY_STORYTIME, CANCELLED_HELP])

    assert payloads == []
    assert source.last_fetch_error is None
    assert "2 calendar rows" in source.last_empty_reason
    assert "recurring=1" in source.last_empty_reason
    assert "cancelled=1" in source.last_empty_reason


async def test_hard_cap_per_library_bounds_the_run_and_reports_it() -> None:
    source, payloads = await _fetch(
        OaklandLibrarySource, [CHAIR_YOGA, DIWALI, MEET_THE_AUTHOR], max_events=2
    )

    assert [e["title"] for e in payloads] == ["Chair Yoga", "Diwali Celebration"]
    assert "Event cap reached" in source.last_fetch_error


# ---------------------------------------------------------------------------
# Crawl: window, pagination, caps, partial failures
# ---------------------------------------------------------------------------


async def test_requests_the_horizon_window_page_by_page_with_an_honest_user_agent() -> None:
    source, requests = _paged_source(
        {
            1: _page([CHAIR_YOGA, WEEKLY_STORYTIME], page=1, pages=3, count=5),
            2: _page([DIWALI, CANCELLED_HELP], page=2, pages=3, count=5),
            3: _page([MEET_THE_AUTHOR], page=3, pages=3, count=5),
        }
    )

    payloads = await source.fetch_events(today=TODAY)

    assert [str(r.url) for r in requests] == [
        f"{OAKLAND_SEARCH}?startDate=2026-11-12&endDate=2026-11-26&limit=50&page={n}"
        for n in (1, 2, 3)
    ]
    assert all(r.headers["user-agent"] == USER_AGENT for r in requests)
    assert [e["title"] for e in payloads] == [
        "Chair Yoga", "Diwali Celebration", MEET_THE_AUTHOR["definition"]["title"],
    ]
    assert source.requests_made == 3
    assert source.last_filter_counts == {"recurring": 1, "cancelled": 1}
    assert source.last_fetch_error is None


async def test_each_library_calls_its_own_gateway_path() -> None:
    source, requests = _paged_source({1: _page([GUINEA_PIGS])}, SanJoseLibrarySource)

    payloads = await source.fetch_events(today=TODAY)

    assert requests[0].url.path == "/v2/libraries/sjpl/events/search"
    assert _only(payloads)["source_name"] == "san_jose_library"


async def test_request_cap_stops_the_crawl_and_reports_it_incomplete() -> None:
    pages = {n: _page([CHAIR_YOGA], page=n, pages=20, count=1000) for n in range(1, 21)}
    source, requests = _paged_source(pages, max_pages=2)

    payloads = await source.fetch_events(today=TODAY)

    assert len(requests) == 2
    assert len(payloads) == 1
    assert "cap" in source.last_fetch_error.lower()


async def test_fewer_rows_than_the_gateway_counted_is_reported_incomplete() -> None:
    """``limit`` above 50 is echoed but not honoured: ``pages`` then understates the crawl."""
    source, requests = _paged_source(
        {1: _page([CHAIR_YOGA, DIWALI], page=1, pages=1, count=5, limit=100)}
    )

    payloads = await source.fetch_events(today=TODAY)

    assert len(requests) == 1
    assert len(payloads) == 2
    assert "Read 2 of 5 rows" in source.last_fetch_error


async def test_a_failed_later_page_keeps_earlier_events_and_reports_a_partial_fetch() -> None:
    source, requests = _paged_source({1: _page([CHAIR_YOGA], page=1, pages=3, count=120), 2: 404})

    payloads = await source.fetch_events(today=TODAY)

    assert len(requests) == 2
    assert [e["title"] for e in payloads] == ["Chair Yoga"]
    assert "HTTPStatusError" in source.last_fetch_error


async def test_a_garbled_later_page_is_a_partial_fetch_too() -> None:
    source, _ = _paged_source(
        {1: _page([CHAIR_YOGA], page=1, pages=2, count=60), 2: "<html>maintenance</html>"}
    )

    payloads = await source.fetch_events(today=TODAY)

    assert len(payloads) == 1
    assert "not valid JSON" in source.last_fetch_error


async def test_a_failed_first_page_raises_so_the_worker_marks_the_source_failing() -> None:
    # SFPL is not on this gateway and answers 403; any first-page error must surface.
    source, _ = _paged_source({1: 403})

    with pytest.raises(httpx.HTTPStatusError):
        await source.fetch_events(today=TODAY)


async def test_missing_pagination_metadata_is_reported_not_assumed_complete() -> None:
    page = _page([CHAIR_YOGA])
    del page["events"]["pagination"]
    source, requests = _paged_source({1: page})

    payloads = await source.fetch_events(today=TODAY)

    assert len(requests) == 1
    assert len(payloads) == 1
    assert "Pagination metadata missing" in source.last_fetch_error
