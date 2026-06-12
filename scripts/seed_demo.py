"""Seed the database with realistic demo events for local exploration.

Usage:
    .venv/bin/python scripts/seed_demo.py [--reset]

Idempotent: skips events whose (source_name, source_event_id) already exists.
With --reset, deletes existing events first.
"""
from __future__ import annotations

import argparse
import sys
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from random import Random

from sqlalchemy import delete
from sqlmodel import Session, select

from app.core.database import engine
from app.models.event import Event

VENUES = [
    ("Chase Center", "1 Warriors Way, San Francisco, CA", -122.3878, 37.7680),
    ("The Fillmore", "1805 Geary Blvd, San Francisco, CA", -122.4329, 37.7842),
    ("Bill Graham Civic Auditorium", "99 Grove St, San Francisco, CA", -122.4178, 37.7785),
    ("Fox Theater Oakland", "1807 Telegraph Ave, Oakland, CA", -122.2705, 37.8086),
    ("The Independent", "628 Divisadero St, San Francisco, CA", -122.4378, 37.7763),
    ("Great American Music Hall", "859 O'Farrell St, San Francisco, CA", -122.4181, 37.7858),
    ("SFJAZZ Center", "201 Franklin St, San Francisco, CA", -122.4226, 37.7762),
    ("Cobb's Comedy Club", "915 Columbus Ave, San Francisco, CA", -122.4119, 37.8027),
    ("Dolores Park", "Dolores St, San Francisco, CA", -122.4275, 37.7596),
    ("Oracle Park", "24 Willie Mays Plaza, San Francisco, CA", -122.3893, 37.7786),
    ("The Chapel", "777 Valencia St, San Francisco, CA", -122.4214, 37.7595),
    ("Ferry Building", "1 Ferry Building, San Francisco, CA", -122.3933, 37.7956),
    ("The Greek Theatre Berkeley", "2001 Gayley Rd, Berkeley, CA", -122.2543, 37.8736),
    ("SFMOMA", "151 3rd St, San Francisco, CA", -122.4006, 37.7857),
    ("California Academy of Sciences", "55 Music Concourse Dr, San Francisco, CA", -122.4663, 37.7699),
    ("Bottom of the Hill", "1233 17th St, San Francisco, CA", -122.3979, 37.7651),
    ("Stern Grove", "19th Ave & Sloat Blvd, San Francisco, CA", -122.4768, 37.7351),
    ("Crissy Field", "1199 East Beach, San Francisco, CA", -122.4661, 37.8030),
    ("Twin Peaks Tavern", "401 Castro St, San Francisco, CA", -122.4350, 37.7619),
    ("Public Works", "161 Erie St, San Francisco, CA", -122.4194, 37.7700),
]

EVENT_TEMPLATES = [
    {
        "title": "Phoebe Bridgers — Reunion Tour",
        "description": "Indie rock icon returns to the Bay with the full band and a string quartet.",
        "categories": ["Music"],
        "tags": ["#LiveMusic", "#Indie", "#Chill"],
        "source_name": "ticketmaster",
        "source_tier": 1,
        "image_url": "https://images.unsplash.com/photo-1501386761578-eac5c94b800a?auto=format&fit=crop&w=800&q=70",
        "price": "78.00",
    },
    {
        "title": "Warriors vs. Lakers",
        "description": "Pacific Division rivalry game at Chase Center. Doors open 90 min before tip-off.",
        "categories": ["Sports"],
        "tags": ["#Sports", "#HighEnergy", "#Spectator"],
        "source_name": "ticketmaster",
        "source_tier": 1,
        "image_url": "https://images.unsplash.com/photo-1546519638-68e109498ffc?auto=format&fit=crop&w=800&q=70",
        "price": "150.00",
    },
    {
        "title": "Hannibal Buress: Truth & Consequence Tour",
        "description": "Hannibal Buress brings his deadpan storytelling to Cobb's for two nights.",
        "categories": ["Comedy"],
        "tags": ["#Comedy", "#Standup", "#NightOut"],
        "source_name": "ticketmaster",
        "source_tier": 1,
        "image_url": "https://images.unsplash.com/photo-1585699324551-f6c309eedeca?auto=format&fit=crop&w=800&q=70",
        "price": "45.00",
    },
    {
        "title": "Sunday Streets — Mission",
        "description": "Valencia Street closed to cars, open to people. Music, food trucks, and pop-up vendors all afternoon.",
        "categories": ["Festival"],
        "tags": ["#Outdoors", "#Free", "#Family", "#FoodAndDrink"],
        "source_name": "funcheap_sf",
        "source_tier": 2,
        "image_url": "https://images.unsplash.com/photo-1533174072545-7a4b6ad7a6c3?auto=format&fit=crop&w=800&q=70",
        "price": "0",
    },
    {
        "title": "Honey Soundsystem · 16 Year Anniversary",
        "description": "Resident DJ collective takes over Public Works with all-night house and techno.",
        "categories": ["Nightlife"],
        "tags": ["#Nightlife", "#Techno", "#HighEnergy", "#LateNight"],
        "source_name": "19hz",
        "source_tier": 2,
        "image_url": "https://images.unsplash.com/photo-1571266028243-d220c6a48a08?auto=format&fit=crop&w=800&q=70",
        "price": "25.00",
    },
    {
        "title": "Free Movie Night: Past Lives at Dolores Park",
        "description": "Bring a blanket. Outdoor screening starts at sundown. Hosted by SF Rec & Park.",
        "categories": ["Film"],
        "tags": ["#Free", "#Outdoors", "#Chill", "#Date"],
        "source_name": "dothebay",
        "source_tier": 2,
        "image_url": "https://images.unsplash.com/photo-1485846234645-a62644f84728?auto=format&fit=crop&w=800&q=70",
        "price": "0",
    },
    {
        "title": "SFMOMA First Thursday — Free Evening",
        "description": "Galleries open until 9pm with free admission. New Diebenkorn retrospective on view.",
        "categories": ["Arts & Theatre"],
        "tags": ["#Art", "#Free", "#Intellectual", "#Date"],
        "source_name": "sfstation",
        "source_tier": 2,
        "image_url": "https://images.unsplash.com/photo-1532453288672-3a27e9be9efd?auto=format&fit=crop&w=800&q=70",
        "price": "0",
    },
    {
        "title": "Bay Area Founders & Funders Mixer",
        "description": "Pre-seed and seed-stage founders meet check-writing angels. Capped at 60 attendees.",
        "categories": ["Business"],
        "tags": ["#Tech", "#Networking", "#Social"],
        "source_name": "luma",
        "source_tier": 2,
        "image_url": "https://images.unsplash.com/photo-1528605248644-14dd04022da1?auto=format&fit=crop&w=800&q=70",
        "price": "15.00",
    },
    {
        "title": "Stern Grove Festival — Toro y Moi",
        "description": "Free outdoor concert in the eucalyptus grove. Picnic-friendly. Arrive by 1pm for a lawn spot.",
        "categories": ["Music", "Festival"],
        "tags": ["#LiveMusic", "#Outdoors", "#Free", "#Family"],
        "source_name": "funcheap_sf",
        "source_tier": 2,
        "image_url": "https://images.unsplash.com/photo-1459749411175-04bf5292ceea?auto=format&fit=crop&w=800&q=70",
        "price": "0",
    },
    {
        "title": "Berkeley Hiking Group — Fire Trails Loop",
        "description": "Weekly 5-mile loop in Tilden Regional Park. All paces welcome. Meet at the Brazilian Building.",
        "categories": ["Outdoors"],
        "tags": ["#Outdoors", "#Wellness", "#Free", "#Social"],
        "source_name": "meetup",
        "source_tier": 1,
        "image_url": "https://images.unsplash.com/photo-1551632811-561732d1e306?auto=format&fit=crop&w=800&q=70",
        "price": "0",
    },
    {
        "title": "SFJAZZ — Esperanza Spalding Quartet",
        "description": "Three-time Grammy winner returns with a new acoustic ensemble. Two sets nightly.",
        "categories": ["Music"],
        "tags": ["#LiveMusic", "#Jazz", "#Date", "#Intellectual"],
        "source_name": "ticketmaster",
        "source_tier": 1,
        "image_url": "https://images.unsplash.com/photo-1415201364774-f6f0bb35f28f?auto=format&fit=crop&w=800&q=70",
        "price": "65.00",
    },
    {
        "title": "Castro Theatre — The Princess Bride 35mm",
        "description": "Sing-along screening on the historic 35mm projector. Costumes encouraged.",
        "categories": ["Film"],
        "tags": ["#Film", "#NightOut", "#Family"],
        "source_name": "sfstation",
        "source_tier": 2,
        "image_url": "https://images.unsplash.com/photo-1489599849927-2ee91cede3ba?auto=format&fit=crop&w=800&q=70",
        "price": "18.00",
    },
    {
        "title": "Minnesota Street Project — First Saturday Open Studios",
        "description": "30+ artists open their studios with new work. Wine reception in the courtyard.",
        "categories": ["Arts & Theatre"],
        "tags": ["#Art", "#Free", "#Social", "#Date"],
        "source_name": "minnesotastreet",
        "source_tier": 2,
        "image_url": "https://images.unsplash.com/photo-1577083552431-6e5fd01988ec?auto=format&fit=crop&w=800&q=70",
        "price": "0",
    },
    {
        "title": "The Independent — Japanese Breakfast",
        "description": "Michelle Zauner's indie-pop project on tour for the new album. Sold out fast last visit.",
        "categories": ["Music"],
        "tags": ["#LiveMusic", "#Indie", "#Date"],
        "source_name": "ticketmaster",
        "source_tier": 1,
        "image_url": "https://images.unsplash.com/photo-1493225457124-a3eb161ffa5f?auto=format&fit=crop&w=800&q=70",
        "price": "42.00",
    },
    {
        "title": "Mission Bowling Club — Tuesday Night Trivia",
        "description": "Free to play, $50 bar tab to winning team. Bowling lanes available between rounds.",
        "categories": ["Social"],
        "tags": ["#Social", "#Free", "#NightOut", "#FoodAndDrink"],
        "source_name": "dothebay",
        "source_tier": 2,
        "image_url": "https://images.unsplash.com/photo-1517649763962-0c623066013b?auto=format&fit=crop&w=800&q=70",
        "price": "0",
    },
    {
        "title": "Alamo Drafthouse — Spirited Away Anniversary",
        "description": "20th anniversary screening with Studio Ghibli-themed cocktails on the menu.",
        "categories": ["Film"],
        "tags": ["#Film", "#Date", "#Chill"],
        "source_name": "eventbrite",
        "source_tier": 1,
        "image_url": "https://images.unsplash.com/photo-1542204625-ca960d2050ae?auto=format&fit=crop&w=800&q=70",
        "price": "22.00",
    },
    {
        "title": "Crissy Field Sunset Yoga",
        "description": "All levels welcome. BYO mat. Class moves to nearby studio if it's foggy.",
        "categories": ["Wellness"],
        "tags": ["#Wellness", "#Outdoors", "#Free"],
        "source_name": "meetup",
        "source_tier": 1,
        "image_url": "https://images.unsplash.com/photo-1506126613408-eca07ce68773?auto=format&fit=crop&w=800&q=70",
        "price": "0",
    },
    {
        "title": "Outside Lands — Day 2",
        "description": "Headliners include Tyler, the Creator and Mitski. Polo Field stage closes at 10pm sharp.",
        "categories": ["Music", "Festival"],
        "tags": ["#LiveMusic", "#Festival", "#HighEnergy", "#Outdoors"],
        "source_name": "ticketmaster",
        "source_tier": 1,
        "image_url": "https://images.unsplash.com/photo-1470229722913-7c0e2dbbafd3?auto=format&fit=crop&w=800&q=70",
        "price": "195.00",
    },
    {
        "title": "Ferry Building — Saturday Farmers Market",
        "description": "100+ vendors with everything from oysters to wood-fired pizza. Live music on the plaza.",
        "categories": ["Food"],
        "tags": ["#FoodAndDrink", "#Free", "#Family", "#Outdoors"],
        "source_name": "dothebay",
        "source_tier": 2,
        "image_url": "https://images.unsplash.com/photo-1534723452862-4c874018d66d?auto=format&fit=crop&w=800&q=70",
        "price": "0",
    },
    {
        "title": "r/AskSF Meetup — Coffee at Sightglass",
        "description": "Monthly community meetup. Look for the group at the bar with the orange tag.",
        "categories": ["Social"],
        "tags": ["#Social", "#Free", "#Newcomers"],
        "source_name": "reddit",
        "source_tier": 3,
        "image_url": "https://images.unsplash.com/photo-1554118811-1e0d58224f24?auto=format&fit=crop&w=800&q=70",
        "price": "0",
    },
]


def _make_event(template: dict, *, venue: tuple, start_at: datetime, suffix: str) -> Event:
    venue_name, address, lon, lat = venue
    return Event(
        title=template["title"],
        description=template["description"],
        start_at=start_at,
        end_at=start_at + timedelta(hours=2, minutes=30),
        source_name=template["source_name"],
        source_tier=template["source_tier"],
        source_event_id=f"demo-{suffix}",
        external_url=f"https://example.com/event/{suffix}",
        venue_name=venue_name,
        raw_address=address,
        location=f"SRID=4326;POINT({lon} {lat})",
        categories=template["categories"],
        tags=template["tags"],
        price=Decimal(template["price"]) if template["price"] else None,
        currency="USD" if template["price"] and template["price"] != "0" else None,
        image_url=template["image_url"],
        status="scheduled",
    )


def seed(*, reset: bool = False) -> None:
    rng = Random(42)
    now = datetime.now(timezone.utc).replace(minute=0, second=0, microsecond=0)

    with Session(engine) as session:
        if reset:
            session.execute(delete(Event))
            session.commit()
            print("[seed] reset: deleted all existing events")

        existing_keys = set(
            session.exec(select(Event.source_name, Event.source_event_id)).all()
        )

        inserted = 0
        skipped = 0
        for index, template in enumerate(EVENT_TEMPLATES):
            for offset_idx in range(2):
                day_offset = rng.randint(1, 14)
                hour = rng.choice([11, 14, 17, 19, 20, 21, 22])
                start_at = (now + timedelta(days=day_offset)).replace(hour=hour)
                venue = rng.choice(VENUES)
                suffix = f"{index}-{offset_idx}-{template['source_name']}"
                key = (template["source_name"], f"demo-{suffix}")
                if key in existing_keys:
                    skipped += 1
                    continue
                session.add(_make_event(template, venue=venue, start_at=start_at, suffix=suffix))
                inserted += 1

        # A handful of same-day events so the "Tonight" preset and "tonight"
        # concierge queries have results immediately after seeding.
        true_now = datetime.now(timezone.utc)
        for tonight_idx, hours_ahead in enumerate((1, 3, 5)):
            template = EVENT_TEMPLATES[tonight_idx % len(EVENT_TEMPLATES)]
            venue = rng.choice(VENUES)
            suffix = f"tonight-{tonight_idx}-{template['source_name']}"
            key = (template["source_name"], f"demo-{suffix}")
            if key in existing_keys:
                skipped += 1
                continue
            session.add(
                _make_event(
                    template,
                    venue=venue,
                    start_at=true_now + timedelta(hours=hours_ahead),
                    suffix=suffix,
                )
            )
            inserted += 1
        session.commit()

    print(f"[seed] inserted={inserted} skipped={skipped} total_templates={len(EVENT_TEMPLATES)}")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--reset", action="store_true", help="Delete existing events before seeding")
    args = parser.parse_args()
    seed(reset=args.reset)
    return 0


if __name__ == "__main__":
    sys.exit(main())
