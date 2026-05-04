from app.ingestion.registry import SourceRegistry
from app.ingestion.ticketmaster import TicketmasterSource


def test_source_registry_registers_ticketmaster() -> None:
    registry = SourceRegistry()
    registry.register("ticketmaster", TicketmasterSource)

    assert registry.list_sources() == ["ticketmaster"]
    assert registry.get("ticketmaster") is TicketmasterSource


def test_ticketmaster_mapping_to_canonical_event_payload() -> None:
    source = TicketmasterSource(api_key="test-key")
    raw_event = {
        "id": "tm_123",
        "name": "Bay Lights Festival",
        "url": "https://ticketmaster.example/events/tm_123",
        "info": "A waterfront music and arts event.",
        "dates": {
            "start": {"dateTime": "2026-06-01T02:00:00Z"},
            "end": {"dateTime": "2026-06-01T05:00:00Z"},
            "status": {"code": "onsale"},
            "timezone": "America/Los_Angeles",
        },
        "priceRanges": [{"min": 45.00, "currency": "USD"}],
        "images": [
            {"url": "https://img.example/small.jpg", "width": 320, "height": 180},
            {"url": "https://img.example/large.jpg", "width": 1920, "height": 1080},
        ],
        "classifications": [
            {
                "segment": {"name": "Music"},
                "genre": {"name": "Rock"},
                "subGenre": {"name": "Alternative"},
            }
        ],
        "_embedded": {
            "venues": [
                {
                    "name": "Pier 70",
                    "address": {"line1": "420 22nd St"},
                    "city": {"name": "San Francisco"},
                    "state": {"stateCode": "CA"},
                    "postalCode": "94107",
                    "country": {"name": "United States"},
                    "location": {"latitude": "37.7577", "longitude": "-122.3872"},
                }
            ],
            "attractions": [{"name": "Headliner Artist"}],
        },
    }

    mapped = source._map_ticketmaster_event(raw_event)
    assert mapped is not None
    assert mapped["source_name"] == "ticketmaster"
    assert mapped["source_tier"] == 1
    assert mapped["source_event_id"] == "tm_123"
    assert mapped["title"] == "Bay Lights Festival"
    assert mapped["location"] == "POINT(-122.3872 37.7577)"
    assert "Music" in mapped["categories"]
    assert "Headliner Artist" in mapped["tags"]
    assert mapped["status"] == "scheduled"


def test_ticketmaster_skips_events_without_coordinates() -> None:
    source = TicketmasterSource(api_key="test-key")
    raw_event = {
        "name": "No Geo Event",
        "dates": {"start": {"dateTime": "2026-06-01T02:00:00Z"}},
        "_embedded": {"venues": [{"name": "Unknown Venue"}]},
    }

    mapped = source._map_ticketmaster_event(raw_event)
    assert mapped is None
