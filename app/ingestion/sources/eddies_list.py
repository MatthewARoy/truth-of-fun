"""
Eddie's List source - curated SF Bay Area events newsletter, ingested over IMAP.

The newsletter is "Via Email Only" - no public web archive of event content.
Live fetch requires IMAP mailbox credentials (IMAP_HOST / IMAP_USER /
IMAP_PASSWORD env vars); the parse path is fully testable by injecting raw
RFC822 messages via ``fetch_events(messages=[...])``.

Compliance posture (see docs/input-agents/source-newsletters-eddies-list.md):
metadata extraction and deep-linking only - a short snippet is retained for
search/attribution, never the full newsletter body.
"""

from __future__ import annotations

import asyncio
import email
import email.policy
import html as html_module
import imaplib
import re
from contextlib import suppress
from datetime import datetime, timedelta, timezone
from email.message import Message
from email.utils import parseaddr, parsedate_to_datetime
from typing import Any

from app.core.config import get_settings
from app.ingestion.contracts import CanonicalEvent
from app.ingestion.contracts import ComplianceModel
from app.ingestion.contracts import LocationModel
from app.ingestion.contracts import OffersModel
from app.ingestion.contracts import OrganizerModel
from app.ingestion.contracts import QualityModel
from app.ingestion.contracts import SourceMetadata
from app.ingestion.input_agent import InputAgentSource
from app.ingestion.scraper_utils import (
    DEFAULT_SF_LAT,
    DEFAULT_SF_LON,
    SF_TZ,
    parse_datetime_flexible,
    parse_price,
    strip_html_tags,
)
from app.ingestion.venue_cache import lookup_venue_coordinates

# Live fetch requires IMAP credentials - cannot run against the real mailbox
# without access. The parser itself is covered by fixture-message tests.
TESTABLE = False
REQUIRES_IMAP_CREDENTIALS = True

_MAX_ISSUES = 10
_MAX_ITEMS_PER_ISSUE = 50
_SNIPPET_MAX_CHARS = 280
_IMAP_LOOKBACK_DAYS = 30

# An item must carry an explicit calendar date ("June 12", "2026-06-12");
# items without one are editorial prose, not events, and are dropped rather
# than given a fabricated date.
_EXPLICIT_DATE_RE = re.compile(
    r"\b(?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\.?\s+\d{1,2}\b"
    r"|\b\d{4}-\d{2}-\d{2}\b",
    re.IGNORECASE,
)

# "... @ 8pm — The Chapel, 777 Valencia St. $25." -> venue text after the dash
_VENUE_AFTER_DASH_RE = re.compile(r"[—–-]\s*([^.$\n]+)")

_HEADING_SPLIT_RE = re.compile(r"<h[2-4][^>]*>", re.IGNORECASE)
_HEADING_BODY_RE = re.compile(r"(?s)(.*?)</h[2-4]>(.*)", re.IGNORECASE)
_HREF_RE = re.compile(r"""href=["'](https?://[^"']+)["']""", re.IGNORECASE)
_URL_IN_TEXT_RE = re.compile(r"https?://\S+")


class EddiesListSource(InputAgentSource):
    """
    Eddie's List: San Francisco Bay Area curated events newsletter.

    Pipeline: IMAP fetch (or injected messages) -> per-issue item extraction
    (HTML headings or plain-text blocks) -> canonical events with
    metadata-only retention and "Eddie's List" attribution.
    """

    source_name = "eddies_list"
    source_tier = 3

    def __init__(
        self,
        *,
        allowed_senders: list[str] | None = None,
        imap_host: str | None = None,
        imap_port: int | None = None,
        imap_user: str | None = None,
        imap_password: str | None = None,
        imap_mailbox: str | None = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(**kwargs)
        settings = get_settings()
        configured_senders = (
            allowed_senders
            if allowed_senders is not None
            else settings.eddies_list_allowed_senders
        )
        self._allowed_senders = [s.strip().lower() for s in configured_senders if s.strip()]
        self._imap_host = imap_host or settings.imap_host
        self._imap_port = imap_port or settings.imap_port
        self._imap_user = imap_user or settings.imap_user
        self._imap_password = imap_password or settings.imap_password
        self._imap_mailbox = imap_mailbox or settings.imap_mailbox

    # ------------------------------------------------------------------
    # Discovery: mailbox (or injected messages) -> candidate item dicts
    # ------------------------------------------------------------------

    async def discover_candidates(self, **kwargs: Any) -> list[Any]:
        messages = kwargs.get("messages")
        if messages is None:
            if not (self._imap_host and self._imap_user and self._imap_password):
                return []
            messages = await asyncio.to_thread(self._fetch_imap_messages)

        candidates: list[dict[str, Any]] = []
        for raw_message in list(messages)[:_MAX_ISSUES]:
            candidates.extend(self._extract_issue_items(raw_message))
        return candidates

    async def extract_candidate(self, candidate: Any) -> dict[str, Any] | None:
        return candidate if isinstance(candidate, dict) else None

    def _fetch_imap_messages(self) -> list[bytes]:
        """Fetch recent newsletter issues from the configured mailbox."""
        messages: list[bytes] = []
        connection = imaplib.IMAP4_SSL(self._imap_host, self._imap_port)
        try:
            connection.login(self._imap_user, self._imap_password)
            connection.select(self._imap_mailbox, readonly=True)
            since = (
                datetime.now(timezone.utc) - timedelta(days=_IMAP_LOOKBACK_DAYS)
            ).strftime("%d-%b-%Y")
            for sender in self._allowed_senders:
                status, data = connection.search(None, "FROM", f'"{sender}"', "SINCE", since)
                if status != "OK" or not data or not data[0]:
                    continue
                for message_id in data[0].split()[-_MAX_ISSUES:]:
                    status, payload = connection.fetch(message_id, "(RFC822)")
                    if status == "OK" and payload and isinstance(payload[0], tuple):
                        messages.append(payload[0][1])
        finally:
            with suppress(Exception):
                connection.logout()
        return messages

    # ------------------------------------------------------------------
    # Issue parsing
    # ------------------------------------------------------------------

    def _extract_issue_items(self, raw_message: bytes | str) -> list[dict[str, Any]]:
        if isinstance(raw_message, str):
            raw_message = raw_message.encode("utf-8", errors="replace")
        message = email.message_from_bytes(raw_message, policy=email.policy.default)

        sender_address = parseaddr(str(message.get("From", "")))[1].lower()
        if not self._is_allowed_sender(sender_address):
            return []

        issue_date = self.utc_now()
        with suppress(Exception):
            parsed_date = parsedate_to_datetime(str(message.get("Date", "")))
            if parsed_date is not None:
                issue_date = parsed_date.astimezone(timezone.utc)
        issue_subject = str(message.get("Subject", "")).strip()

        html_body, text_body = self._extract_bodies(message)
        if html_body:
            items = self._items_from_html(html_body)
        elif text_body:
            items = self._items_from_text(text_body)
        else:
            return []

        for item in items:
            item["issue_date"] = issue_date
            item["issue_subject"] = issue_subject
        return items[:_MAX_ITEMS_PER_ISSUE]

    def _is_allowed_sender(self, address: str) -> bool:
        if not address or not self._allowed_senders:
            return False
        domain = address.rsplit("@", 1)[-1]
        for allowed in self._allowed_senders:
            if address == allowed or domain == allowed or domain.endswith("." + allowed):
                return True
        return False

    def _extract_bodies(self, message: Message) -> tuple[str | None, str | None]:
        html_body: str | None = None
        text_body: str | None = None
        parts = message.walk() if message.is_multipart() else [message]
        for part in parts:
            if part.get_content_maintype() != "text":
                continue
            with suppress(Exception):
                content = part.get_content()
                if not isinstance(content, str) or not content.strip():
                    continue
                if part.get_content_subtype() == "html" and html_body is None:
                    html_body = content
                elif part.get_content_subtype() == "plain" and text_body is None:
                    text_body = content
        return html_body, text_body

    def _items_from_html(self, body: str) -> list[dict[str, Any]]:
        """Each <h2>-<h4> heading with a link starts an item; the blurb runs to the next heading."""
        items: list[dict[str, Any]] = []
        for section in _HEADING_SPLIT_RE.split(body)[1:]:
            match = _HEADING_BODY_RE.match(section)
            if not match:
                continue
            heading_html, rest = match.group(1), match.group(2)
            title = html_module.unescape(strip_html_tags(heading_html))
            if not title:
                continue
            link_match = _HREF_RE.search(heading_html) or _HREF_RE.search(rest)
            if not link_match:
                continue
            blurb = html_module.unescape(strip_html_tags(rest))
            items.append(
                {
                    "title": title,
                    "source_url": link_match.group(1),
                    "blurb": blurb,
                }
            )
        return items

    def _items_from_text(self, body: str) -> list[dict[str, Any]]:
        """Plain-text fallback: blank-line-separated blocks with a title line and a link."""
        items: list[dict[str, Any]] = []
        for block in re.split(r"\n\s*\n", body):
            lines = [line.strip() for line in block.splitlines() if line.strip()]
            if len(lines) < 2:
                continue
            url_match = _URL_IN_TEXT_RE.search(block)
            if not url_match:
                continue
            title = lines[0]
            blurb_lines = [
                line for line in lines[1:] if not _URL_IN_TEXT_RE.fullmatch(line)
            ]
            items.append(
                {
                    "title": title,
                    "source_url": url_match.group(0),
                    "blurb": " ".join(blurb_lines),
                }
            )
        return items

    # ------------------------------------------------------------------
    # Normalization
    # ------------------------------------------------------------------

    def normalize_raw(self, raw_item: dict[str, Any]) -> CanonicalEvent | None:
        title = raw_item.get("title")
        source_url = raw_item.get("source_url")
        blurb = raw_item.get("blurb") or ""
        if not isinstance(title, str) or not title.strip() or not source_url:
            return None

        # Editorial prose without an explicit calendar date is not an event.
        if not _EXPLICIT_DATE_RE.search(blurb):
            return None

        issue_date = raw_item.get("issue_date")
        if not isinstance(issue_date, datetime):
            issue_date = self.utc_now()
        reference_date = issue_date.astimezone(SF_TZ).date()

        start_time = parse_datetime_flexible(blurb, reference_date=reference_date)
        if start_time is None:
            return None
        # Year rollover: a December issue announcing "January 3" means next year.
        if start_time.date() < reference_date - timedelta(days=60):
            with suppress(ValueError):
                start_time = start_time.replace(year=start_time.year + 1)

        venue_name, address_line1 = self._parse_venue(blurb)
        coords = lookup_venue_coordinates(venue_name)
        lat = coords[0] if coords else DEFAULT_SF_LAT
        lon = coords[1] if coords else DEFAULT_SF_LON

        price, is_free = parse_price(blurb)

        snippet = blurb.strip()[:_SNIPPET_MAX_CHARS] or None

        return CanonicalEvent(
            source=SourceMetadata(
                source_id="eddies_list",
                source_record_id=str(source_url),
                source_url=source_url,
                ingested_at=self.utc_now(),
                last_seen_at=self.utc_now(),
                capture_mode="email_ingest",
                crawl_job_id=f"eddies-list-{int(self.utc_now().timestamp())}",
            ),
            title=title.strip(),
            description=snippet,
            start_time=start_time.astimezone(timezone.utc),
            location=LocationModel(
                venue_name=venue_name,
                address_line1=address_line1,
                city="San Francisco",
                region="CA",
                lat=lat,
                lon=lon,
                location_confidence=0.9 if coords else (0.5 if venue_name else 0.3),
            ),
            offers=OffersModel(price_min=price, is_free=is_free),
            organizer=OrganizerModel(name="Eddie's List"),
            category_tags=["curated", "local"],
            compliance=ComplianceModel(
                retention_policy="metadata_only",
                copyright_risk="medium",
                notes="Snippet retained for search/attribution only; full newsletter body is never republished.",
            ),
            quality=QualityModel(
                record_confidence=0.7 if coords else 0.55,
                needs_review=coords is None,
            ),
        )

    def _parse_venue(self, blurb: str) -> tuple[str | None, str | None]:
        """Extract venue (and trailing address) from '... — The Chapel, 777 Valencia St. ...'."""
        match = _VENUE_AFTER_DASH_RE.search(blurb)
        if not match:
            return None, None
        segment = match.group(1).strip().rstrip(",")
        if not segment:
            return None, None
        venue, _, address = segment.partition(",")
        venue = venue.strip()
        address = address.strip() or None
        return (venue or None), address
