"""Tests for the Stern Grove Festival lineup scraper."""

from __future__ import annotations

import asyncio

from app.ingestion.scraper_utils import SF_TZ
from app.ingestion.sources.sterngrove import SternGroveSource


# Trimmed from the live 2026 lineup page. Squarespace renders the whole body as
# a single <article> with the season as a flat run of blocks — date, headliner,
# support, status, lottery — rather than one element per concert. The quirks
# below are real: "With" is capitalised on some rows, "&amp;" appears instead of
# "and", one date is a Saturday, and every concert is followed by a "Lottery
# opens <Month Day>" line that must not be mistaken for a concert date.
LINEUP_HTML = """
<html>
  <head><title>Stern Grove Festival 2026 Lineup</title></head>
  <body>
    <article>
      <h1>Lineup</h1>
      <p>The lottery opens six (6) weeks before each concert @ 10am.</p>
      <p class="date">Sunday, June 14</p>
      <h3 class="headliner">Peter Cat Recording Co.</h3>
      <p class="support">With Marinero and DJ TBD</p>
      <p class="status">SOLD OUT</p>
      <p class="lottery">Lottery opens May 3</p>
      <p class="date">Sunday, June 21</p>
      <h3 class="headliner">Bomba Estéreo</h3>
      <p class="support">With La Misa Negra &amp; KEXP DJ Albina Cabrera</p>
      <p class="status">SOLD OUT</p>
      <p class="lottery">Lottery opens May 10</p>
      <p class="date">Sunday, June 28</p>
      <h3 class="headliner">Japanese Breakfast</h3>
      <p class="support">with Leenalchi, DJ Evie Stokes</p>
      <p class="status">SOLD OUT</p>
      <p class="lottery">Lottery opens May 17</p>
      <p class="date">Sunday, July 5</p>
      <h3 class="headliner">Major Lazer</h3>
      <p class="support">with Fijiana, DJ Bad Juuju and KALW DJ Patrick King Most</p>
      <p class="status">SOLD OUT</p>
      <p class="lottery">Lottery opens May 24</p>
      <p class="date">Sunday, July 12</p>
      <h3 class="headliner">SF Symphony</h3>
      <p class="support">with Béla Fleck</p>
      <p class="status">SOLD OUT</p>
      <p class="lottery">Lottery opens May 31</p>
      <p class="date">Sunday, July 19</p>
      <h3 class="headliner">Charley Crockett</h3>
      <p class="support">with Nicki Bluhm and KALW DJ Eryka</p>
      <p class="status">SOLD OUT</p>
      <p class="lottery">Lottery opens June 7</p>
      <p class="date">Sunday, July 26</p>
      <h3 class="headliner">Suki Waterhouse</h3>
      <p class="support">with Charlotte Lawrence, KEXP DJ Cheryl Waters</p>
      <p class="status">SOLD OUT</p>
      <p class="lottery">Lottery opens June 14</p>
      <p class="date">Sunday, August 2</p>
      <h3 class="headliner">Violent Femmes</h3>
      <p class="support">with Tune-Yards and KALW DJ Lady Ryan</p>
      <p class="status">SOLD OUT</p>
      <p class="lottery">Lottery opens June 21</p>
      <p class="date">Sunday, August 9</p>
      <h3 class="headliner">Patti LaBelle</h3>
      <p class="support">with Destani Wolf and KPFA DJ Malachi</p>
      <p class="status">SOLD OUT</p>
      <p class="lottery">Lottery opens June 28</p>
      <p class="date">Saturday, August 15</p>
      <h3 class="headliner">Public Enemy</h3>
      <p class="support">with LaRussell and KPFA DJ Davey D</p>
      <p class="status">SOLD OUT</p>
      <p class="lottery">Lottery opens July 4</p>
      <p class="date">Sunday, August 16</p>
      <h3 class="headliner">Al Green</h3>
      <p class="support">with Goapele, The Glide Ensemble and KALW DJ Wonway Posibul</p>
      <p class="status">SOLD OUT</p>
      <p class="lottery">Lottery opens July 5</p>
    </article>
  </body>
</html>
"""


def test_fetch_events_emits_each_published_concert_date() -> None:
    source = SternGroveSource()

    events = asyncio.run(source.fetch_events(html=LINEUP_HTML))

    assert len(events) == 11
    assert [event["title"] for event in events] == [
        "Peter Cat Recording Co.",
        "Bomba Estéreo",
        "Japanese Breakfast",
        "Major Lazer",
        "SF Symphony",
        "Charley Crockett",
        "Suki Waterhouse",
        "Violent Femmes",
        "Patti LaBelle",
        "Public Enemy",
        "Al Green",
    ]
    public_enemy = events[9]
    assert public_enemy["start_at"].strftime("%A, %Y-%m-%d") == (
        "Saturday, 2026-08-15"
    )


def test_lineup_url_uses_the_selected_season_year() -> None:
    source = SternGroveSource(season_year=2027)

    assert source.lineup_url == "https://www.sterngrove.org/lineup2027"


def test_concert_preserves_lineup_admission_time_and_venue_facts() -> None:
    source = SternGroveSource()

    events = asyncio.run(source.fetch_events(html=LINEUP_HTML))

    violent_femmes = events[7]
    assert violent_femmes["title"] == "Violent Femmes"
    assert "Tune-Yards" not in violent_femmes["title"]
    assert (
        "Opening acts: Tune-Yards and KALW DJ Lady Ryan"
        in violent_femmes["description"]
    )
    assert "advance GA lottery" in violent_femmes["description"]
    assert violent_femmes["is_free"] is True
    assert violent_femmes["price"] == 0.0
    assert violent_femmes["currency"] == "USD"
    assert violent_femmes["start_at"].astimezone(SF_TZ).hour == 14
    assert violent_femmes["end_at"] is None
    assert violent_femmes["venue_name"] == "Sigmund Stern Grove"
    assert violent_femmes["location"] == "POINT(-122.4713 37.7373)"
    assert violent_femmes["location_confidence"] == 0.9


def test_published_concert_time_overrides_the_sourced_fallback() -> None:
    # Season stated explicitly: the year is an input, not sniffed from markup.
    source = SternGroveSource(season_year=2027)
    html = """
    <title>Stern Grove Festival 2027 Lineup</title>
    <article class="eventlist-event">
      <time>Sunday, June 20</time>
      <h2>Future Headliner</h2>
      <p>Concert begins at 3:30pm</p>
    </article>
    """

    events = asyncio.run(source.fetch_events(html=html))

    assert len(events) == 1
    assert events[0]["start_at"].astimezone(SF_TZ).strftime("%H:%M") == "15:30"


def test_season_year_beats_a_stray_year_earlier_in_the_page() -> None:
    """The requested season is authoritative, not the first 20xx in the markup.

    Deriving the year by scanning the HTML means a copyright footer, a nav link
    to a past season, or an "archive 2025" blurb rendered above the lineup
    silently shifts every concert to the wrong year.
    """
    # Ahead of the <title>, so document order genuinely favours the wrong year.
    html = LINEUP_HTML.replace(
        "<head>",
        '<head><meta name="copyright" content="(c) 2019 Stern Grove Festival">',
    )
    source = SternGroveSource(season_year=2026)

    events = asyncio.run(source.discover_candidates(html=html))

    assert events, "expected the lineup to still parse"
    assert all(candidate["date_iso"].startswith("2026-") for candidate in events)


def test_trailing_page_text_does_not_set_the_last_concert_time() -> None:
    """The final block runs to the end of the page; footer prose must not leak in.

    The live page ends with the lottery explanation, whose "@ 10am" landed on a
    continuation line and became Al Green's start time.
    """
    html = LINEUP_HTML.replace(
        "    </article>",
        "      <p>The lottery opens</p>\n"
        "      <p>six (6) weeks before each concert @ 10am</p>\n"
        "    </article>",
    )
    source = SternGroveSource(season_year=2026)

    events = asyncio.run(source.fetch_events(html=html))

    assert len(events) == 11
    assert events[-1]["title"] == "Al Green"
    assert events[-1]["start_at"].astimezone(SF_TZ).hour == 14
