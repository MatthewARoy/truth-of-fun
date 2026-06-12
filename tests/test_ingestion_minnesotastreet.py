"""Tests for Minnesota Street Project scraper."""

from __future__ import annotations

from app.ingestion.sources.minnesotastreet import EVENT_KIND_EXHIBITION
from app.ingestion.sources.minnesotastreet import EVENT_KIND_RECEPTION
from app.ingestion.sources.minnesotastreet import MinnesotaStreetSource
from app.ingestion.sources.minnesotastreet import TESTABLE

# Trimmed from the live Drupal markup at minnesotastreetproject.com/exhibitions.
EXHIBITIONS_HTML = """
<div id="items-container" class="row items-list">
  <div class="item column md-3 sm-6">
    <figure>
<img src="/sites/default/files/styles/small_crop/public/adler.jpg?itok=x" alt="Adler Guerrier: Prim and mottled forms arranged to this end">
</figure>
<h3 class="font-large">
\t<a href="/exhibitions/1275-minnesota-st/adler-guerrier-prim-and-mottled-forms-arranged-end" title="Adler Guerrier: Prim and mottled forms arranged to this end">
\t\t<span class="div-link"></span>
\t\tAdler Guerrier: Prim and mottled forms arranged to this end\t</a>
</h3>
<p class="font-small">
\tJun 6–Jul 18, 2026<br>
\t1275 Minnesota St / re.riddle</p>    </div>

  <div class="item column md-3 sm-6">
    <figure>
<img src="/sites/default/files/styles/small_crop/public/crush.png?itok=y" alt="Virtual Crush">
</figure>
<h3 class="font-large">
\t<a href="/exhibitions/1150-25th-st/virtual-crush" title="Virtual Crush">
\t\t<span class="div-link"></span>
\t\tVirtual Crush\t</a>
</h3>
<p class="font-small">
\tMay 2–Sep 19, 2026<br>
\t1150 25th St / Slash</p>    </div>
</div>
<footer role="contentinfo" class="footer small">
<ul class="footer-nav"><li><a href="/careers">Careers</a></li>
<li><a href="/about#contact">Contact</a></li></ul>
</footer>
"""

# Trimmed from the live Drupal markup at minnesotastreetproject.com/events/all.
EVENTS_HTML = """
<div id="items-container" class="row items-list">
\t<div class="item item-row row event-row">
    \t<div class="column sm-6 md-2 font-small hidden-xs">
\tSat, Jun 13, 4PM-6PM\t<br>
\t\t1275 Minnesota St<br>\tRuth Asawa Lanier, Inc.</div>
<div class="column sm-6 md-3 md-pull-4 visible-sm">
\t<p class="font-small highlight"></p>
\t<h3 class="font-large">
\t\t<a href="/events/ruth-asawa-lanier-inc-wildling-shoe-launch-event" rel="nofollow" title="Ruth Asawa Lanier, Inc, Wildling Shoe Launch Event">
\t\t\tRuth Asawa Lanier, Inc, Wildling Shoe Launch Event\t\t</a>
\t</h3>
</div>
<div class="column sm-6 md-3 md-pull-4 hidden-sm">
\t<p class="font-small highlight"></p>
\t<h3 class="font-large">
\t\t<a href="/events/ruth-asawa-lanier-inc-wildling-shoe-launch-event" rel="nofollow" title="Ruth Asawa Lanier, Inc, Wildling Shoe Launch Event">
\t\t\tRuth Asawa Lanier, Inc, Wildling Shoe Launch Event\t\t</a>
\t</h3>
</div>    </div>
\t<div class="item item-row row event-row">
    \t<div class="column sm-6 md-2 font-small hidden-xs">
\tSat, Jul 11, 4PM-6PM\t<br>
\t\t1150 25th St<br>\tSlash</div>
<div class="column sm-6 md-3 md-pull-4 visible-sm">
\t<p class="font-small highlight">Performance</p>
\t<h3 class="font-large">
\t\t<a href="/events/performance/open-fell" rel="nofollow" title="Open Fell">
\t\t\tOpen Fell\t\t</a>
\t</h3>
</div>    </div>
  <div class="view-footer">
    <a class="highlight" href="/events/past/all">View past events</a>
  </div>
</div>
"""


def test_minnesotastreet_testable() -> None:
    assert TESTABLE is True


def test_minnesotastreet_exhibition_extract_and_normalize() -> None:
    source = MinnesotaStreetSource()
    candidates = source._extract_candidates(EXHIBITIONS_HTML, event_kind=EVENT_KIND_EXHIBITION)
    assert len(candidates) == 2

    ev = candidates[0]
    assert ev["title"] == "Adler Guerrier: Prim and mottled forms arranged to this end"
    assert ev["event_kind"] == EVENT_KIND_EXHIBITION
    assert ev["date_range"] == "Jun 6–Jul 18, 2026"
    assert ev["venue_text"] == "1275 Minnesota St"
    assert ev["gallery"] == "re.riddle"
    # Deep link to the exhibition detail page, not the listing page.
    assert ev["source_url"] == (
        "https://minnesotastreetproject.com/exhibitions/1275-minnesota-st/"
        "adler-guerrier-prim-and-mottled-forms-arranged-end"
    )

    normalized = source.normalize_raw(ev)
    assert normalized is not None
    assert normalized.all_day is True
    assert normalized.start_time.year == 2026
    assert normalized.end_time is not None
    assert normalized.end_time.year == 2026
    payload = normalized.to_legacy_event_payload(source_tier=source.source_tier)
    assert payload["source_name"] == "minnesotastreet"
    assert "exhibition_window" in normalized.category_tags

    second = candidates[1]
    assert second["title"] == "Virtual Crush"
    assert second["venue_text"] == "1150 25th St"
    assert second["gallery"] == "Slash"


def test_minnesotastreet_exhibition_skips_nav_links() -> None:
    source = MinnesotaStreetSource()
    candidates = source._extract_candidates(EXHIBITIONS_HTML, event_kind=EVENT_KIND_EXHIBITION)
    titles = {c["title"] for c in candidates}
    assert "Careers" not in titles
    assert "Contact" not in titles


def test_minnesotastreet_reception_extract_and_normalize() -> None:
    source = MinnesotaStreetSource()
    candidates = source._extract_candidates(EVENTS_HTML, event_kind=EVENT_KIND_RECEPTION)
    assert len(candidates) == 2

    ev = candidates[0]
    assert ev["title"] == "Ruth Asawa Lanier, Inc, Wildling Shoe Launch Event"
    assert ev["event_kind"] == EVENT_KIND_RECEPTION
    assert ev["time_text"] == "Sat, Jun 13, 4PM-6PM"
    assert ev["venue_text"] == "1275 Minnesota St"
    assert ev["gallery"] == "Ruth Asawa Lanier, Inc."
    # Deep link to the event detail page, not the listing page.
    assert ev["source_url"] == (
        "https://minnesotastreetproject.com/events/ruth-asawa-lanier-inc-wildling-shoe-launch-event"
    )

    normalized = source.normalize_raw(ev)
    assert normalized is not None
    assert normalized.all_day is False
    assert "opening_reception" in normalized.category_tags
    # 4PM America/Los_Angeles (PDT in June) == 23:00 UTC.
    assert normalized.start_time.hour == 23
    assert normalized.start_time.day == 13
    # End time comes from the explicit "4PM-6PM" range (6PM PDT == 01:00 UTC),
    # never a hardcoded default.
    assert normalized.end_time is not None
    assert normalized.end_time.hour == 1

    second = candidates[1]
    assert second["title"] == "Open Fell"
    assert second["venue_text"] == "1150 25th St"
    assert second["gallery"] == "Slash"


def test_minnesotastreet_reception_without_end_time_has_no_end() -> None:
    source = MinnesotaStreetSource()
    ev = {
        "title": "Single Time Reception",
        "source_url": "https://minnesotastreetproject.com/events/single-time-reception",
        "source_record_id": "reception-single-time-reception",
        "event_kind": EVENT_KIND_RECEPTION,
        "time_text": "Sat, Jun 13, 5PM",
        "venue_text": "1275 Minnesota St",
        "gallery": "",
        "date_range": None,
    }
    normalized = source.normalize_raw(ev)
    assert normalized is not None
    # No explicit end time on the page => no fabricated end time.
    assert normalized.end_time is None
