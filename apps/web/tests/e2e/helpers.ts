import type { Page, Route } from "@playwright/test";

/** The browser's API base. Specs intercept requests to it; no backend runs. */
export const API = process.env.NEXT_PUBLIC_API_BASE_URL || "http://127.0.0.1:8000";

export const SESSION = { token: "fixture-token", email: "me@example.test", userId: 1 };

export async function signInFixture(page: Page, session = SESSION) {
  await page.addInitScript((value) => {
    // Only seed once: a later reload must keep whatever the app stored since.
    if (!sessionStorage.getItem("e2e-seeded")) {
      sessionStorage.setItem("e2e-seeded", "1");
      localStorage.setItem("tof_auth", JSON.stringify(value));
    }
  }, session);
}

export function storedSession(page: Page) {
  return page.evaluate(() => JSON.parse(localStorage.getItem("tof_auth") ?? "null"));
}

export function eventFixture(id: number, overrides: Record<string, unknown> = {}) {
  return {
    id, title: `Event ${id}`, description: "An event", start_at: "2030-07-05T03:00:00Z",
    start_time_is_estimated: false, end_at: null, external_url: null,
    venue_name: "SF Venue", tags: [], categories: [], image_url: null,
    price: null, currency: null, status: "scheduled", people_interested: 0,
    distance_miles: null, lat: null, lng: null, location_confidence: 1, is_free: false,
    city: null, region: null,
    ...overrides,
  };
}

export const REGIONS = {
  regions: [
    { id: "sf", label: "San Francisco", upcoming_count: 1234, cities: [{ name: "San Francisco", upcoming_count: 1234 }] },
    { id: "east_bay", label: "East Bay", upcoming_count: 412, cities: [
      { name: "Oakland", upcoming_count: 230 }, { name: "Berkeley", upcoming_count: 120 },
    ] },
    { id: "peninsula", label: "Peninsula", upcoming_count: 88, cities: [{ name: "Palo Alto", upcoming_count: 40 }] },
    { id: "south_bay", label: "South Bay", upcoming_count: 150, cities: [{ name: "San Jose", upcoming_count: 110 }] },
    { id: "north_bay", label: "North Bay", upcoming_count: 0, cities: [] },
  ],
};

type ExploreMock = {
  events?: (params: URLSearchParams) => unknown[];
  regions?: (route: Route) => Promise<void> | void;
};

/**
 * Intercept GET /events and GET /regions. Returns every /events query the
 * page made, in order, so a spec can assert exactly what was sent.
 */
export async function mockExploreApi(page: Page, options: ExploreMock = {}) {
  const queries: URLSearchParams[] = [];
  await page.route(`${API}/regions`, (route) =>
    options.regions ? options.regions(route) : route.fulfill({ json: REGIONS })
  );
  await page.route((url) => url.href.startsWith(`${API}/events?`) || url.href === `${API}/events`, (route) => {
    const params = new URL(route.request().url()).searchParams;
    queries.push(params);
    return route.fulfill({ json: options.events ? options.events(params) : [eventFixture(1)] });
  });
  return {
    queries,
    last: () => Object.fromEntries(queries[queries.length - 1] ?? []),
  };
}

const PNG_1X1 = Buffer.from(
  "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNkYPhfDwAChwGA60e6kgAAAABJRU5ErkJggg==",
  "base64"
);

/** Answer map tiles and hotlinked event images locally so specs never touch the network. */
export async function stubRemoteImages(page: Page) {
  const png = (route: Route) => route.fulfill({ contentType: "image/png", body: PNG_1X1 });
  await page.route(/^https:\/\/[a-d]\.basemaps\.cartocdn\.com\//, png);
  await page.route(/^https:\/\/images\.example\//, png);
}

/**
 * Record Content-Security-Policy violations: both the DOM event (fires for
 * every blocked load, inline script or eval) and the console error Chromium
 * prints. Call before navigating; read with `violations()`.
 */
export async function trackCspViolations(page: Page) {
  const consoleErrors: string[] = [];
  page.on("console", (message) => {
    const text = message.text();
    if (/Content Security Policy|Content-Security-Policy/i.test(text)) consoleErrors.push(text);
  });
  await page.addInitScript(() => {
    const store = (window as unknown as { __csp: string[] }).__csp ??= [];
    document.addEventListener("securitypolicyviolation", (event) => {
      store.push(`${event.violatedDirective} blocked ${event.blockedURI || "inline"}`);
    });
  });
  return async () => [
    ...consoleErrors,
    ...(await page.evaluate(() => (window as unknown as { __csp?: string[] }).__csp ?? [])),
  ];
}
