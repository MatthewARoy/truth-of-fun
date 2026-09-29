import json
import logging
import os
import tempfile
from datetime import datetime, timedelta, timezone
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
_DEEP_PAGING_LIMIT = 1000
_DEFAULT_HORIZON_DAYS = 180
_MIN_WINDOW = timedelta(days=1)
_MAX_REQUESTS_PER_RUN = 80

# Bay Area DMA ID (San Francisco-Oakland-San Jose)
_BAY_AREA_DMA_ID = "382"

def _format_api_timestamp(value: datetime) -> str:
    return value.astimezone(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')


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
        horizon_days: int = _DEFAULT_HORIZON_DAYS,
        now: datetime | None = None,
        **kwargs: Any,
    ) -> list[dict[str, Any]]:
        """Read bounded date partitions plus undated postponements.

        Discovery supports date filters, not a modified-date delta cursor.
        Completion is acknowledged only after the worker's durable commit.
        """
        self._pending_sync_timestamp = None
        self.last_fetch_error = None
        if size < 1 or horizon_days < 1:
            raise ValueError("Ticketmaster page size and horizon must be positive.")
        page_size = min(size, _MAX_PAGE_SIZE)
        params: dict[str, Any] = {
            "apikey": self._api_key, "countryCode": country_code,
            "dmaId": _BAY_AREA_DMA_ID, "size": page_size, "sort": "date,asc",
        }
        if keyword:
            params["keyword"] = keyword
        if city:
            params["city"] = city
        sync_started_at = _format_api_timestamp(datetime.now(timezone.utc))
        horizon_start = (now or datetime.now(timezone.utc)).replace(microsecond=0)
        if horizon_start.tzinfo is None:
            raise ValueError("Ticketmaster now must include a timezone.")
        pending = [(horizon_start, horizon_start + timedelta(days=horizon_days))]
        page_limit = (_DEEP_PAGING_LIMIT + page_size - 1) // page_size
        canonical_events: list[dict[str, Any]] = []
        seen_event_ids: set[str] = set()
        requests_made = 0

        async def read_page(page_params: dict[str, Any]) -> dict[str, Any] | None:
            nonlocal requests_made
            if requests_made >= _MAX_REQUESTS_PER_RUN:
                self.last_fetch_error = f"request budget of {_MAX_REQUESTS_PER_RUN} exhausted"
                return None
            requests_made += 1
            try:
                return await self._fetch_page(page_params)
            except Exception as exc:
                # Never expose an API key embedded in an exception/request URL.
                self.last_fetch_error = f"{type(exc).__name__} on page {page_params['page']}"
                return None

        def append_events(payload: dict[str, Any]) -> None:
            raw_events = payload.get("_embedded", {}).get("events", [])
            if not isinstance(raw_events, list):
                return
            for raw in raw_events:
                if not isinstance(raw, dict):
                    continue
                mapped = self._map_ticketmaster_event(raw)
                if mapped is None:
                    continue
                event_id = mapped.get("source_event_id")
                if event_id:
                    if event_id in seen_event_ids:
                        continue
                    seen_event_ids.add(event_id)
                canonical_events.append(mapped)

        while pending and self.last_fetch_error is None:
            window_start, window_end = pending.pop()
            current_page, total_pages = 0, 1
            split = False
            while current_page < total_pages and current_page < page_limit:
                payload = await read_page({
                    **params, "startDateTime": _format_api_timestamp(window_start),
                    "endDateTime": _format_api_timestamp(window_end), "page": current_page,
                    "includeTBA": "no", "includeTBD": "no",
                })
                if payload is None:
                    break
                page_info = payload.get("page", {})
                total_pages = page_info.get("totalPages", 1)
                total_elements = page_info.get("totalElements", 0)
                if current_page == 0 and (total_elements > _DEEP_PAGING_LIMIT or total_pages > page_limit):
                    if window_end - window_start > _MIN_WINDOW:
                        midpoint = (window_start + (window_end - window_start) / 2).replace(microsecond=0)
                        # Read earlier dates first; inclusive boundaries dedupe by ID.
                        pending.extend([(midpoint, window_end), (window_start, midpoint)])
                        split = True
                        break
                    logger.warning("Ticketmaster dense window: only the first 1000 are reachable")
                append_events(payload)
                current_page += 1
            if not split and self.last_fetch_error is None and (
                current_page < total_pages or total_elements > _DEEP_PAGING_LIMIT
            ):
                self.last_fetch_error = "Pagination cap reached in minimum date window; search incomplete"

        # Date filters exclude undated events. Read them separately without
        # a horizon filter, so a postponement reaches the original stored row.
        if self.last_fetch_error is None:
            current_page, total_pages = 0, 1
            total_elements = 0
            while current_page < total_pages and current_page < page_limit:
                payload = await read_page({**params, "includeTBA": "only", "page": current_page})
                if payload is None:
                    break
                page_info = payload.get("page", {})
                total_pages = page_info.get("totalPages", 1)
                total_elements = page_info.get("totalElements", 0)
                append_events(payload)
                current_page += 1
            if self.last_fetch_error is None and (current_page < total_pages or total_elements > _DEEP_PAGING_LIMIT):
                self.last_fetch_error = "Pagination cap reached in undated pass; search incomplete"

        if self.last_fetch_error is None and not keyword and not city and country_code == "US":
            self._pending_sync_timestamp = sync_started_at
        elif self.last_fetch_error:
            logger.warning("Ticketmaster incomplete fetch: %s", self.last_fetch_error)
        logger.info("Ticketmaster fetched %d events in %d requests", len(canonical_events), requests_made)
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

        status_code = (
            dates.get("status", {}).get("code", "onsale")
            if isinstance(dates.get("status"), dict)
            else "onsale"
        )

        start_at = self._parse_datetime(
            date_time=start.get("dateTime"),
            local_date=start.get("localDate"),
            local_time=start.get("localTime"),
            timezone_name=timezone_name,
        )
        if start_at is None and status_code.lower() == "postponed":
            # Postponing without a new date blanks dates.start. The date the show
            # was postponed from is still published, and storing it alongside
            # status=postponed is true; dropping the event instead left the
            # stored row claiming the show was on.
            initial = dates.get("initialStartDate", {})
            if isinstance(initial, dict):
                start_at = self._parse_datetime(
                    date_time=initial.get("dateTime"),
                    local_date=initial.get("localDate"),
                    local_time=initial.get("localTime"),
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
        # Ticketmaster's dates.status.code. Only cancelled and postponed mean the
        # show is not happening as listed: a rescheduled event carries its new
        # date in dates.start, and offsale only means Ticketmaster isn't selling
        # tickets right now (sold out, sales closed, box office only).
        mapping = {
            "onsale": "scheduled",
            "offsale": "scheduled",
            "cancelled": "cancelled",
            "rescheduled": "scheduled",
            "postponed": "postponed",
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
