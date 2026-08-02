/**
 * Product-local timezone, mirroring `app/core/localtime.py` on the backend.
 *
 * Event times belong to the city the event is in, not to whoever is reading
 * the page. This matters most for a shared itinerary: the recipient may open
 * it from another timezone — or from a plane on the way here — and "doors at
 * 8pm" has to keep meaning 8pm at the venue. It also keeps the rendered page
 * agreeing with the plain-text version, which the server renders in this zone.
 */
export const LOCAL_TIME_ZONE = "America/Los_Angeles";

export function formatLocalTime(value: string | Date): string {
  return new Date(value).toLocaleTimeString(undefined, {
    hour: "numeric",
    minute: "2-digit",
    timeZone: LOCAL_TIME_ZONE,
  });
}

export function formatLocalDay(value: string | Date): string {
  return new Date(value).toLocaleDateString(undefined, {
    weekday: "short",
    month: "short",
    day: "numeric",
    timeZone: LOCAL_TIME_ZONE,
  });
}
