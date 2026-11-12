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

/**
 * The interface is English-only, and dates are formatted with one fixed
 * locale rather than the reader's. Server-rendered pages (event detail) must
 * produce the same text on the server and in the browser or hydration fails,
 * and it keeps the page agreeing with the server-rendered plain-text plans.
 */
const DISPLAY_LOCALE = "en-US";

export function formatLocalTime(value: string | Date): string {
  return new Date(value).toLocaleTimeString(DISPLAY_LOCALE, {
    hour: "numeric",
    minute: "2-digit",
    timeZone: LOCAL_TIME_ZONE,
  });
}

export function formatLocalDay(value: string | Date): string {
  return new Date(value).toLocaleDateString(DISPLAY_LOCALE, {
    weekday: "short",
    month: "short",
    day: "numeric",
    timeZone: LOCAL_TIME_ZONE,
  });
}

export function formatLocalLongDay(value: string | Date): string {
  return new Date(value).toLocaleDateString(DISPLAY_LOCALE, {
    weekday: "long",
    month: "long",
    day: "numeric",
    year: "numeric",
    timeZone: LOCAL_TIME_ZONE,
  });
}

const DATE_KEY = /^(\d{4})-(\d{2})-(\d{2})$/;

/** True for a real calendar date written as YYYY-MM-DD. */
export function isDateKey(value: string | null | undefined): value is string {
  const match = value ? DATE_KEY.exec(value) : null;
  if (!match) return false;
  const [year, month, day] = [Number(match[1]), Number(match[2]), Number(match[3])];
  const probe = new Date(Date.UTC(year, month - 1, day));
  return probe.getUTCFullYear() === year && probe.getUTCMonth() === month - 1 && probe.getUTCDate() === day;
}

/** The product-local calendar date (YYYY-MM-DD) at the given instant. */
export function localDateKey(value: string | Date = new Date()): string {
  const parts = new Intl.DateTimeFormat("en-CA", {
    timeZone: LOCAL_TIME_ZONE, year: "numeric", month: "2-digit", day: "2-digit",
  }).formatToParts(new Date(value));
  const get = (type: string) => parts.find((part) => part.type === type)?.value ?? "";
  return `${get("year")}-${get("month")}-${get("day")}`;
}

/** Minutes the product-local zone is ahead of UTC at `instant` (negative in California). */
function localOffsetMinutes(instant: number): number {
  const parts = new Intl.DateTimeFormat("en-US", {
    timeZone: LOCAL_TIME_ZONE, hourCycle: "h23",
    year: "numeric", month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit", second: "2-digit",
  }).formatToParts(new Date(instant));
  const get = (type: string) => Number(parts.find((part) => part.type === type)?.value);
  const asUtc = Date.UTC(get("year"), get("month") - 1, get("day"), get("hour"), get("minute"), get("second"));
  return Math.round((asUtc - Math.floor(instant / 1000) * 1000) / 60_000);
}

/**
 * The instant a product-local calendar day begins, wherever the reader is.
 * "Saturday" in a date filter means Saturday in California: a visitor
 * searching from Tokyo must get the same events as one in Oakland.
 */
export function startOfLocalDay(dateKey: string): Date {
  const match = DATE_KEY.exec(dateKey);
  if (!match) throw new RangeError(`Not a YYYY-MM-DD date: ${dateKey}`);
  const wallClock = Date.UTC(Number(match[1]), Number(match[2]) - 1, Number(match[3]));
  // Resolve the offset twice: the first guess can sit on the other side of a
  // daylight-saving change (which happens at 2am, never at midnight).
  let instant = wallClock - localOffsetMinutes(wallClock) * 60_000;
  instant = wallClock - localOffsetMinutes(instant) * 60_000;
  return new Date(instant);
}

/** The calendar date `days` after `dateKey` (calendar arithmetic, DST-safe). */
export function addDaysToDateKey(dateKey: string, days: number): string {
  const match = DATE_KEY.exec(dateKey);
  if (!match) throw new RangeError(`Not a YYYY-MM-DD date: ${dateKey}`);
  const shifted = new Date(Date.UTC(Number(match[1]), Number(match[2]) - 1, Number(match[3]) + days));
  return shifted.toISOString().slice(0, 10);
}

/**
 * API bounds for events on the product-local days `from` through `to`
 * inclusive. The API's `end_at` is an inclusive bound on the start time, so
 * the window closes one millisecond before the following midnight.
 */
export function localDayRange(from: string, to: string = from): { start_at: string; end_at: string } {
  const last = to < from ? from : to;
  return {
    start_at: startOfLocalDay(from).toISOString(),
    end_at: new Date(startOfLocalDay(addDaysToDateKey(last, 1)).getTime() - 1).toISOString(),
  };
}

/** "Sat, Nov 14" for a YYYY-MM-DD date, independent of the reader's zone. */
export function formatDateKey(dateKey: string): string {
  return formatLocalDay(new Date(startOfLocalDay(dateKey).getTime() + 12 * 3_600_000));
}
