import type { EventDetailResponse } from "@truth-of-fun/api-client";
import { hasVenuePin, safeExternalUrl, safeImageUrl } from "@/lib/event-format";
import { REGION_IDS } from "@/lib/explore-params";
import { localDateKey } from "@/lib/localtime";
import { summarize } from "@/lib/metadata";
import { absoluteUrl } from "@/lib/site";

const EVENT_STATUS: Record<string, string> = {
  cancelled: "https://schema.org/EventCancelled",
  postponed: "https://schema.org/EventPostponed",
};

/**
 * schema.org `Event` structured data for search engines. Only facts the
 * listing actually states are emitted: an estimated start becomes a bare date
 * (never an invented clock time), and an unknown price produces no offer.
 */
export function eventJsonLd(event: EventDetailResponse): Record<string, unknown> {
  const image = safeImageUrl(event.image_url);
  const tickets = safeExternalUrl(event.external_url);
  const inBayArea = REGION_IDS.some((region) => region === event.region);
  const hasPlace = Boolean(event.venue_name || event.raw_address || event.city);
  const priceKnown = event.is_free === true || (typeof event.price === "number" && event.price >= 0);

  return {
    "@context": "https://schema.org",
    "@type": "Event",
    name: event.title,
    url: absoluteUrl(`/events/${event.id}`),
    startDate: event.start_time_is_estimated ? localDateKey(event.start_at) : event.start_at,
    ...(event.end_at && !event.start_time_is_estimated ? { endDate: event.end_at } : {}),
    eventStatus: EVENT_STATUS[event.status] ?? "https://schema.org/EventScheduled",
    ...(event.description ? { description: summarize(event.description, 500) } : {}),
    ...(image ? { image: [image] } : {}),
    ...(hasPlace ? {
      location: {
        "@type": "Place",
        ...(event.venue_name ? { name: event.venue_name } : {}),
        address: event.raw_address?.trim() || {
          "@type": "PostalAddress",
          ...(event.city ? { addressLocality: event.city } : {}),
          ...(inBayArea ? { addressRegion: "CA", addressCountry: "US" } : {}),
        },
        ...(hasVenuePin(event) ? {
          geo: { "@type": "GeoCoordinates", latitude: event.lat, longitude: event.lng },
        } : {}),
      },
    } : {}),
    ...(priceKnown ? {
      offers: {
        "@type": "Offer",
        price: event.is_free === true ? 0 : event.price,
        priceCurrency: /^[A-Za-z]{3}$/.test(event.currency ?? "") ? event.currency!.toUpperCase() : "USD",
        ...(tickets ? { url: tickets } : {}),
      },
    } : {}),
    ...(event.performers?.length ? {
      performer: event.performers.map((name) => ({ "@type": "PerformingGroup", name })),
    } : {}),
    ...(event.organizer_name ? { organizer: { "@type": "Organization", name: event.organizer_name } } : {}),
  };
}

/** Serialize for a <script type="application/ld+json">, neutralising any markup in listing text. */
export function serializeJsonLd(data: unknown): string {
  return JSON.stringify(data).replace(/</g, "\\u003c");
}
