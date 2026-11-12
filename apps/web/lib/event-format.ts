import type { EventResponse } from "@truth-of-fun/api-client";
import { formatLocalDay, formatLocalLongDay, formatLocalTime } from "@/lib/localtime";

type EventTiming = Pick<EventResponse, "start_at" | "start_time_is_estimated">;

/**
 * A placeholder hour rendered as a clock time reads as fact and gets planned
 * around, so estimated starts show the day and say the time is unpublished.
 * The date itself is always real.
 */
export function eventStartLabel(event: EventTiming): string {
  return event.start_time_is_estimated
    ? `${formatLocalDay(event.start_at)} · time TBA`
    : `${formatLocalDay(event.start_at)} · ${formatLocalTime(event.start_at)}`;
}

export function eventLongStartLabel(event: EventTiming): string {
  return event.start_time_is_estimated
    ? `${formatLocalLongDay(event.start_at)} · time to be announced`
    : `${formatLocalLongDay(event.start_at)} at ${formatLocalTime(event.start_at)}`;
}

export type StatusNotice = { label: string; className: string; explanation: string };

/**
 * A postponed or cancelled show keeps the date it was listed for, and that is
 * not a date to plan around: say what happened, and call the time the original.
 */
export function statusNotice(status: string): StatusNotice | null {
  switch (status) {
    case "postponed":
      return {
        label: "Postponed",
        className: "border-amber-700 bg-amber-900/40 text-amber-100",
        explanation: "This event has been postponed. The date below is the original one; check the organizer's page for the new date.",
      };
    case "cancelled":
      return {
        label: "Cancelled",
        className: "border-rose-700 bg-rose-900/40 text-rose-100",
        explanation: "This event has been cancelled. The date below is when it was originally scheduled.",
      };
    default:
      return null;
  }
}

/**
 * "Free", a formatted price, or null when the source published no price.
 * Unknown is not free: never print a price the listing did not state.
 */
export function priceLabel(event: Pick<EventResponse, "price" | "currency" | "is_free">): string | null {
  if (event.is_free === true || event.price === 0) return "Free";
  if (typeof event.price !== "number" || !Number.isFinite(event.price) || event.price < 0) return null;
  const currency = /^[A-Za-z]{3}$/.test(event.currency ?? "") ? event.currency!.toUpperCase() : "USD";
  try {
    return new Intl.NumberFormat("en-US", {
      style: "currency", currency,
      minimumFractionDigits: Number.isInteger(event.price) ? 0 : 2,
      maximumFractionDigits: 2,
    }).format(event.price);
  } catch {
    return `$${event.price}`;
  }
}

/**
 * Event links and images come from third-party listings. Only http(s) may
 * become an href: a `javascript:` or `data:` URL from a scraped page must
 * never be clickable.
 */
export function safeExternalUrl(value: string | null | undefined): string | null {
  if (!value) return null;
  try {
    const url = new URL(value.trim());
    return url.protocol === "https:" || url.protocol === "http:" ? url.toString() : null;
  } catch {
    return null;
  }
}

/** Hotlinked images must be https (mixed content is blocked, and the CSP only allows https). */
export function safeImageUrl(value: string | null | undefined): string | null {
  if (!value) return null;
  try {
    const url = new URL(value.trim());
    return url.protocol === "https:" ? url.toString() : null;
  } catch {
    return null;
  }
}

/** "Venue · City", without repeating a city the venue name already ends with. */
export function placeLabel(event: Pick<EventResponse, "venue_name" | "city">): string {
  const venue = event.venue_name?.trim();
  const city = event.city?.trim();
  if (venue && city) return venue.toLowerCase().includes(city.toLowerCase()) ? venue : `${venue} · ${city}`;
  return venue || city || "Venue to be announced";
}

/** Coordinates below this confidence are a city-centre fallback, not the venue. */
export const VENUE_PIN_MIN_CONFIDENCE = 0.5;

export function hasVenuePin(event: Pick<EventResponse, "lat" | "lng" | "location_confidence">): boolean {
  return typeof event.lat === "number" && typeof event.lng === "number"
    && (event.location_confidence === undefined || event.location_confidence === null
      || event.location_confidence >= VENUE_PIN_MIN_CONFIDENCE);
}

/** Google Maps directions to the venue, or null when there is nothing to navigate to. */
export function directionsUrl(
  event: Pick<EventResponse, "lat" | "lng" | "venue_name" | "city" | "location_confidence"> & { raw_address?: string | null }
): string | null {
  let destination: string | null = null;
  if (hasVenuePin(event)) destination = `${event.lat},${event.lng}`;
  else if (event.raw_address?.trim()) destination = event.raw_address.trim();
  else if (event.venue_name?.trim()) destination = [event.venue_name.trim(), event.city?.trim()].filter(Boolean).join(", ");
  if (!destination) return null;
  return `https://www.google.com/maps/dir/?api=1&destination=${encodeURIComponent(destination)}`;
}

export function distanceLabel(miles: number | null | undefined): string | null {
  if (typeof miles !== "number" || !Number.isFinite(miles) || miles < 0) return null;
  if (miles < 0.1) return "Under 0.1 mi away";
  return `${miles < 10 ? miles.toFixed(1) : Math.round(miles)} mi away`;
}
