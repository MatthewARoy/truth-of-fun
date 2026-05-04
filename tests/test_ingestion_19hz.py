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
