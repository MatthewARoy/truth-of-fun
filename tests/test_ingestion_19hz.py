from __future__ import annotations

from app.ingestion.sources.nineteen_hz import NineteenHzSource


def test_19hz_extract_rows_and_normalize_private_location() -> None:
    source = NineteenHzSource()
    html = """
    <table>
      <tr>
        <td>Fri: Jan 16 (10pm-4am)</td>
        <td><a href="https://19hz.info/sample-event">Techno Night @ TBA</a></td>
        <td>house, techno</td>
      </tr>
    </table>
    """
    rows = source._extract_rows(html)
    assert len(rows) == 1
    normalized = source.normalize_raw(rows[0])
    assert normalized is not None

    payload = normalized.to_legacy_event_payload(source_tier=source.source_tier)
    assert payload["source_name"] == "19hz"
    assert payload["source_tier"] == 2
    assert payload["venue_name"] == "TBA"
    assert payload["title"] == "Techno Night"
    assert payload["location"] == "POINT(-122.4194 37.7749)"
    assert normalized.location.location_is_private is True
    # The listing has no cost column or cost text, so unknown is correct.
    assert normalized.offers.price_min is None
    assert normalized.offers.currency is None


def test_parse_venue_city_reads_the_parenthesised_city() -> None:
    """19hz venue strings carry their city in parentheses before the genres."""
    source = NineteenHzSource()
    assert source._parse_venue_city("Fuze (San Jose) house, disco, tech house") == "San Jose"
    assert source._parse_venue_city("The Stud (San Francisco) afrobeats, house") == "San Francisco"
    assert source._parse_venue_city("TBA") is None


def test_out_of_town_venue_is_not_placed_at_sf_city_hall() -> None:
    """A Sacramento venue must not land on SF's centroid (regression for #17).

    Unresolvable venues used to fall back to DEFAULT_SF_LAT/LON, so Sacramento,
    San Jose and Santa Cruz events all appeared inside an SF radius search.
    """
    source = NineteenHzSource()
    html = """
    <table>
      <tr>
        <td>Sun: Aug 2 (5pm-11pm)</td>
        <td><a href="https://19hz.info/e/1">Romain Garcia @ Darling Aviary (Sacramento) progressive house</a></td>
        <td>progressive house</td>
      </tr>
    </table>
    """
    rows = source._extract_rows(html)
    normalized = source.normalize_raw(rows[0])
    assert normalized is not None

    assert normalized.location.city == "Sacramento"
    payload = normalized.to_legacy_event_payload(source_tier=source.source_tier)
    assert payload["location"] != "POINT(-122.4194 37.7749)"


def test_sf_venue_without_a_cache_entry_still_reports_san_francisco() -> None:
    """The common case keeps working: an unknown SF venue stays in SF."""
    source = NineteenHzSource()
    html = """
    <table>
      <tr>
        <td>Sun: Aug 2 (2pm-10pm)</td>
        <td><a href="https://19hz.info/e/2">Sweet Tooth Fest @ Some New Spot (San Francisco) house</a></td>
        <td>house</td>
      </tr>
    </table>
    """
    rows = source._extract_rows(html)
    normalized = source.normalize_raw(rows[0])
    assert normalized is not None
    assert normalized.location.city == "San Francisco"


def test_private_location_confidence_stays_below_the_radius_threshold() -> None:
    """A TBA venue is still a centroid guess (review P2).

    GET /events excludes location_confidence < 0.5 from radius search, but a
    private/TBA venue was assigned exactly 0.5 while sitting on the SF
    centroid, so it passed the inclusive >= comparison and stayed in results.
    """
    source = NineteenHzSource()
    html = """
    <table>
      <tr>
        <td>Sun: Aug 2 (10pm-4am)</td>
        <td><a href="https://19hz.info/e/9">Secret Party @ TBA</a></td>
        <td>techno</td>
      </tr>
    </table>
    """
    rows = source._extract_rows(html)
    normalized = source.normalize_raw(rows[0])
    assert normalized is not None
    assert normalized.location.location_is_private is True
    assert normalized.location.location_confidence < 0.5


def test_price_column_becomes_a_price_not_a_category() -> None:
    """19hz's third column is cost/age, not genres.

    The connector read it as tags, so `categories` filled up with strings like
    "$22-37 | 21+" (visible across the live table) while price stayed null.
    Contrary to the earlier survey for #19, this source does carry cost text.
    """
    source = NineteenHzSource()
    html = """
    <table>
      <tr>
        <td>Sun: Aug 2 (2pm-10pm)</td>
        <td><a href="https://19hz.info/e/5">Sweet Tooth Fest @ The Stud (San Francisco) house</a></td>
        <td>$22-37 | 21+</td>
        <td>Some Artist</td>
        <td>Instagram Page</td>
        <td>2026/08/02</td>
      </tr>
    </table>
    """
    rows = source._extract_rows(html)
    normalized = source.normalize_raw(rows[0])
    assert normalized is not None

    assert normalized.offers.price_min == 22.0
    assert normalized.offers.currency == "USD"
    assert normalized.offers.is_free is False
    assert "$22-37 | 21+" not in normalized.category_tags


def test_free_19hz_listing_is_marked_free() -> None:
    """A free show in the cost column sets is_free, not a null price."""
    source = NineteenHzSource()
    html = """
    <table>
      <tr>
        <td>Sun: Aug 2 (2pm-10pm)</td>
        <td><a href="https://19hz.info/e/6">Park Party @ Somewhere (San Francisco) house</a></td>
        <td>Free | All ages</td>
        <td>Some Artist</td>
        <td>Instagram Page</td>
        <td>2026/08/02</td>
      </tr>
    </table>
    """
    rows = source._extract_rows(html)
    normalized = source.normalize_raw(rows[0])
    assert normalized is not None
    assert normalized.offers.is_free is True
    assert normalized.offers.price_min == 0.0
