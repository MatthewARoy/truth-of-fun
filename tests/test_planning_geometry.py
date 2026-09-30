from datetime import datetime, timezone
import pytest

from app.api.discovery import ItineraryStopResponse, _portable_stops
from app.services.itinerary import StopLocation, render_itinerary_text
from app.services.planning import PlanningPlace, UserStop, resolve_search_area, travel_minutes


def test_per_leg_distance_and_mode_change_allowance():
    start = StopLocation(lat=37.76, lng=-122.50)
    near = StopLocation(lat=37.7643, lng=-122.50)
    far = StopLocation(lat=37.847, lng=-122.50)
    assert travel_minutes(start, near, "driving")[0] < travel_minutes(start, far, "driving")[0] / 2
    assert travel_minutes(start, far, "walking")[0] > travel_minutes(start, far, "driving")[0]
    assert travel_minutes(start, StopLocation(lat=37.76, lng=-122.4, location_confidence=0.3), "walking") == (30, False)


def test_mixed_chain_uses_immediate_previous_stop_and_honest_fallback():
    def stop(title, hour, planner=False, estimated=False):
        return ItineraryStopResponse(kind="walk" if planner else "main_event", event_id=None if planner else 1,
            title=title, start_at=datetime(2026,10,2,hour,tzinfo=timezone.utc), end_at=None,
            start_time_is_estimated=estimated, venue_name=title, external_url=None,
            travel_buffer_minutes_before=0, provenance="planner" if planner else "event")
    stops = _portable_stops([(stop("Meet",0,True),StopLocation(lat=37.76,lng=-122.5)),
        (stop("Stroll",1,True),StopLocation(venue_name="Coastal trail")),
        (stop("Show",3),StopLocation(lat=37.76,lng=-122.4)),
        (stop("Time unknown",4,estimated=True),StopLocation(lat=37.76,lng=-122.4001))],travel_mode="walking")
    assert stops[2].travel_buffer_minutes_before == 30
    assert stops[2].travel_estimate is False
    assert stops[2].leave_by.hour == 2 and stops[2].leave_by.minute == 30
    assert stops[3].leave_by is None
    text = render_itinerary_text(title="Mixed plan",stops=stops)
    assert "Added by the planner" in text
    assert "Leave by ~7:30 PM" in text
    assert "time TBA" in text


def test_origin_optional_and_area_resolution_is_explicit():
    assert resolve_search_area("Fun tomorrow") is None
    assert resolve_search_area("Sunset yoga in Oakland") is None
    assert resolve_search_area("west side").radius_miles == 2.5
    origin = PlanningPlace(name="Meet here")
    assert origin.location().lat is None


@pytest.mark.parametrize("patch", [{"start_at":"2026-10-01T17:00:00"}, {"end_at":"2026-10-01T16:00:00-07:00"}])
def test_user_stop_requires_aware_ordered_times(patch):
    with pytest.raises(ValueError):
        UserStop.model_validate({"kind":"walk", "title":"Coastal trail", "place":{"name":"Ocean Beach"},
            "start_at":"2026-10-01T17:00:00-07:00", **patch})
