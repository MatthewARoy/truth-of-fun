import json
import logging
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import httpx

from app.core.config import get_settings
from app.ingestion.base import BaseSource
from app.services.secrets_store import get_secrets_store

logger = logging.getLogger(__name__)

# Pagination / quota safety constants
_MAX_PAGE_SIZE = 200
_MAX_PAGES = 25  # 25 pages * 200 = 5000 events; conserves daily quota

# Bay Area DMA ID (San Francisco-Oakland-San Jose)
_BAY_AREA_DMA_ID = "382"

# Sync state persistence
_SYNC_STATE_PATH = Path(__file__).resolve().parents[2] / ".ticketmaster_sync_state.json"


def _load_last_sync_timestamp() -> str | None:
    """Load completion metadata, not a provider-supported incremental cursor."""
    try:
        data = json.loads(_SYNC_STATE_PATH.read_text())
        ts = data.get("last_sync_timestamp")
        return ts if isinstance(ts, str) else None
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return None


def _save_last_sync_timestamp(timestamp: str) -> None:
    """Atomically record a fetch whose returned events were durably processed."""
    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", dir=_SYNC_STATE_PATH.parent, prefix=".ticketmaster-", delete=False
        ) as handle:
            temporary_path = Path(handle.name)
            json.dump({"last_sync_timestamp": timestamp}, handle)
            handle.flush()
            os.fsync(handle.fileno())
        temporary_path.replace(_SYNC_STATE_PATH)
    finally:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)


class TicketmasterSource(BaseSource):
    """Ingestion provider for the Ticketmaster Discovery API."""

    source_name = "ticketmaster"
    source_tier = 1
    base_url = "https://app.ticketmaster.com/discovery/v2"

    # Set by fetch_events when a page failed and the window was only partially
    # read. Class-level default so a caller can read it on a source that has
    # not run yet.
    last_fetch_error: str | None = None

    def __init__(
        self,
        *,
        api_key: str | None = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(**kwargs)
        settings = get_settings()
        self._aaim_enabled = settings.aaim_enabled
        self._pending_sync_timestamp: str | None = None
        self.last_fetch_was_incremental = False
        self._key_id = "explicit"
        self._api_key = api_key
        if self._api_key:
            return

        if settings.aaim_enabled:
            # The store owns fallback policy. Catching a disabled/exhausted
            # inventory here would silently reuse the environment credential.
            lease = get_secrets_store().get_active_key("ticketmaster")
            self._api_key = lease.api_key
            self._key_id = lease.key_id
        else:
            self._api_key = settings.ticketmaster_api_key
            self._key_id = "env-ticketmaster"

        if not self._api_key:
            raise ValueError("Ticketmaster API key is required.")

    @property
    def usage_key_id(self) -> str:
        """Non-secret identifier for this run's provider-usage telemetry."""
        return self._key_id

    # ------------------------------------------------------------------
    # Single-page fetch (internal helper)
    # ------------------------------------------------------------------

    async def _fetch_page(
        self,
        params: dict[str, Any],
    ) -> dict[str, Any]:
        """Fetch a single page from the Ticketmaster API and report usage."""
        status_code: int | None = None
        last_error: str | None = None
        try:
            payload = await self._get_json(
                f"{self.base_url}/events.json", params=params,
            )
            status_code = 200
            return payload
        except httpx.HTTPStatusError as exc:
            status_code = exc.response.status_code
            last_error = str(exc)
            raise
        except Exception as exc:
            last_error = str(exc)
            raise
        finally:
            if self._aaim_enabled:
                try:
                    # 429s are transient (and retried with backoff in _get_json);
                    # quota exhaustion is tracked via usage counts, so never
                    # permanently disable a key here — there is no re-enable path.
                    get_secrets_store().report_usage(
                        provider="ticketmaster",
                        key_id=self._key_id,
                        calls=1,
                        last_status=status_code,
                        last_error=last_error,
                    )
                except Exception:
                    pass

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def fetch_events(
        self,
        *,
        keyword: str | None = None,
        city: str | None = None,
        country_code: str = "US",
        size: int = _MAX_PAGE_SIZE,
        **kwargs: Any,
    ) -> list[dict[str, Any]]:
        self._pending_sync_timestamp = None
        self.last_fetch_error = None
        if size < 1:
            raise ValueError("Ticketmaster page size must be positive.")
        page_size = min(size, _MAX_PAGE_SIZE)
        params: dict[str, Any] = {
            "apikey": self._api_key,
            "countryCode": country_code,
            "dmaId": _BAY_AREA_DMA_ID,
            "size": page_size,
            "sort": "date,asc",
        }
        if keyword:
            params["keyword"] = keyword
        if city:
            params["city"] = city

        # Discovery v2 documents no modifiedDate parameter. Do not pretend a
        # completion timestamp is a supported delta cursor: replay bounded
        # searches and rely on durable source identity for idempotency.
        # https://developer.ticketmaster.com/products-and-docs/apis/discovery-api/v2/
        logger.info("Ticketmaster full search; prior completion metadata does not filter events")

        sync_started_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

        canonical_events: list[dict[str, Any]] = []
        current_page = 0
        total_pages = 1  # will be updated after first response

        # Discovery v2 requires page*size < 1000 (zero-based page number).
        tm_page_cap = (1000 + page_size - 1) // page_size
        page_limit = min(_MAX_PAGES, tm_page_cap)

        # A failed page means the window was only partially read. Recorded so the
        # cursor is not advanced past events we never saw, and so a caller can
        # tell a half-read window from a legitimately small result.
        self.last_fetch_error = None

        while current_page < total_pages and current_page < page_limit:
            params["page"] = current_page
            try:
                payload = await self._fetch_page(params)
            except Exception as exc:
                # Type and page only: this string is meant to be surfaceable, and
                # the message can carry the `?apikey=` from the failing request.
                # The full exception goes to the log via exc_info.
                self.last_fetch_error = f"{type(exc).__name__} on page {current_page}"
                logger.warning(
                    "Ticketmaster page %d failed, stopping pagination.",
                    current_page,
                    exc_info=True,
                )
                break

            # Extract pagination metadata
            page_info = payload.get("page", {})
            total_pages = page_info.get("totalPages", 1)
            total_elements = page_info.get("totalElements", 0)

            if current_page == 0:
                logger.info(
                    "Ticketmaster: %d total events across %d pages",
                    total_elements,
                    total_pages,
                )

            logger.info(
                "Fetching page %d/%d",
                current_page + 1,
                min(total_pages, _MAX_PAGES),
            )

            # Parse events from this page
            raw_events = payload.get("_embedded", {}).get("events", [])
            if not isinstance(raw_events, list):
                raw_events = []

            for raw_event in raw_events:
                if not isinstance(raw_event, dict):
                    continue
                mapped = self._map_ticketmaster_event(raw_event)
                if mapped is not None:
                    canonical_events.append(mapped)

            current_page += 1

        if self.last_fetch_error is None and current_page < total_pages:
            self.last_fetch_error = (
                f"Pagination cap reached: read {current_page} of {total_pages} pages; "
                "search remains incomplete and will be replayed"
            )

        # A bounded search that hits the provider/quota cap is incomplete. A
        # partitioned crawl is a separate concern; never advertise a cap as a
        # complete sync or skip unseen events behind a fabricated cursor.
        if self.last_fetch_error is None and not keyword and not city and country_code == "US":
            self._pending_sync_timestamp = sync_started_at
        elif self.last_fetch_error:
            logger.warning("Ticketmaster incomplete fetch: %s", self.last_fetch_error)
        logger.info(
            "Ticketmaster fetch complete: %d canonical events from %d pages",
            len(canonical_events),
            current_page,
        )

        return canonical_events

    def acknowledge_persisted(self) -> None:
        """Called by the worker only after the pipeline commit succeeded.

        The file records a fully read search, not an incremental API cursor.
        Failed/partial fetches have no candidate to acknowledge.
        """
        if self._pending_sync_timestamp is None or self.last_fetch_error is not None:
            return
        _save_last_sync_timestamp(self._pending_sync_timestamp)
        self._pending_sync_timestamp = None

    def _map_ticketmaster_event(self, event: dict[str, Any]) -> dict[str, Any] | None:
        venues = event.get("_embedded", {}).get("venues", [])
        venue = venues[0] if venues and isinstance(venues[0], dict) else {}
        geo = venue.get("location", {}) if isinstance(venue, dict) else {}

        latitude = self._to_float(geo.get("latitude"))
        longitude = self._to_float(geo.get("longitude"))
        if latitude is None or longitude is None:
            # Geospatial integrity rule: skip events missing coordinates.
            return None

        dates = event.get("dates", {})
        start = dates.get("start", {}) if isinstance(dates, dict) else {}
        end = dates.get("end", {}) if isinstance(dates, dict) else {}
        timezone_name = event.get("dates", {}).get("timezone")

        start_at = self._parse_datetime(
            date_time=start.get("dateTime"),
            local_date=start.get("localDate"),
            local_time=start.get("localTime"),
            timezone_name=timezone_name,
        )
        if start_at is None:
            return None

        end_at = self._parse_datetime(
            date_time=end.get("dateTime"),
            local_date=end.get("localDate"),
            local_time=end.get("localTime"),
            timezone_name=timezone_name,
        )

        price_ranges = event.get("priceRanges", [])
        primary_price = price_ranges[0] if price_ranges and isinstance(price_ranges[0], dict) else {}

        tags = self._extract_tags(event)
        categories = self._extract_categories(event)
        raw_address = self._format_address(venue)

        status_code = (
            dates.get("status", {}).get("code", "onsale")
            if isinstance(dates.get("status"), dict)
            else "onsale"
        )

        return {
            "title": event.get("name", "Untitled Event"),
            "description": event.get("info") or event.get("pleaseNote"),
            "start_at": start_at,
            "end_at": end_at,
            "source_name": self.source_name,
            "source_tier": self.source_tier,
            "source_event_id": event.get("id"),
            "external_url": event.get("url"),
            "venue_name": venue.get("name") if isinstance(venue, dict) else None,
            "raw_address": raw_address,
            "location": f"POINT({longitude} {latitude})",
            "categories": categories,
            "tags": tags,
            "price": primary_price.get("min"),
            "currency": primary_price.get("currency"),
            "image_url": self._pick_best_image(event.get("images", [])),
            "status": self._normalize_status(status_code),
        }

    def _extract_categories(self, event: dict[str, Any]) -> list[str]:
        categories: list[str] = []
        for item in event.get("classifications", []):
            if not isinstance(item, dict):
                continue
            for key in ("segment", "genre", "subGenre", "type", "subType"):
                value = item.get(key, {})
                if isinstance(value, dict):
                    name = value.get("name")
                    if isinstance(name, str) and name and name not in categories:
                        categories.append(name)
        return categories

    def _extract_tags(self, event: dict[str, Any]) -> list[str]:
        """Ticketmaster exposes no vibe data, so contribute none.

        This previously returned attraction names, which put performer and team
        names ("San Francisco Giants") into the vibe tag space where they
        matched no profile and diluted ranking. Vibe tags for these events come
        from the LLM tagger instead.
        """
        return []

    def _pick_best_image(self, images: Any) -> str | None:
        if not isinstance(images, list) or not images:
            return None
        best = max(
            (img for img in images if isinstance(img, dict) and img.get("url")),
            key=lambda img: (img.get("width", 0) or 0) * (img.get("height", 0) or 0),
            default=None,
        )
        if best is None:
            return None
        return str(best.get("url"))

    def _format_address(self, venue: dict[str, Any]) -> str | None:
        if not isinstance(venue, dict):
            return None
        parts: list[str] = []
        line1 = venue.get("address", {}).get("line1")
        city = venue.get("city", {}).get("name")
        state = venue.get("state", {}).get("stateCode")
        postal = venue.get("postalCode")
        country = venue.get("country", {}).get("name")
        for value in (line1, city, state, postal, country):
            if isinstance(value, str) and value:
                parts.append(value)
        return ", ".join(parts) if parts else None

    def _normalize_status(self, source_status: str) -> str:
        mapping = {
            "onsale": "scheduled",
            "offsale": "cancelled",
            "cancelled": "cancelled",
            "rescheduled": "scheduled",
            "postponed": "scheduled",
        }
        return mapping.get(source_status.lower(), "scheduled")

    def _to_float(self, value: Any) -> float | None:
        if value is None:
            return None
        try:
            return float(value)
        except (TypeError, ValueError):
            return None

    def _parse_datetime(
        self,
        *,
        date_time: Any,
        local_date: Any,
        local_time: Any,
        timezone_name: Any,
    ) -> datetime | None:
        if isinstance(date_time, str) and date_time:
            try:
                return datetime.fromisoformat(date_time.replace("Z", "+00:00"))
            except ValueError:
                return None

        if not isinstance(local_date, str) or not local_date:
            return None

        time_part = local_time if isinstance(local_time, str) and local_time else "00:00:00"
        try:
            parsed = datetime.fromisoformat(f"{local_date}T{time_part}")
        except ValueError:
            return None

        if isinstance(timezone_name, str) and timezone_name:
            try:
                return parsed.replace(tzinfo=ZoneInfo(timezone_name))
            except Exception:
                pass

        return parsed.replace(tzinfo=timezone.utc)
