import { test, expect, type Page } from "@playwright/test";

// The shared itinerary page is what someone opens from a text message, so it
// has to stand on its own: no auth, no app state, nothing carried over from the
// session that built the plan. These tests stub the API at the network layer
// rather than running a backend, keeping the suite hermetic like its siblings.

const API_BASE = process.env.NEXT_PUBLIC_API_BASE_URL || "http://127.0.0.1:8000";

const SHARED_ITINERARY = {
  share_token: "test-token-000000000000000000",
  share_url: "/itinerary/test-token-000000000000000000",
  title: "Date night in Mission — Sat, Aug 8",
  query: "date night in the mission saturday",
  intent: "date_night",
  timeframe: "this_saturday",
  geography: "mission",
  anchor_event_id: 2,
  created_at: "2026-08-02T00:00:00Z",
  expires_at: "2099-08-16T00:00:00Z",
  itinerary: [
    {
      kind: "pre_event_drink",
      event_id: 1,
      title: "Happy hour at True Laurel",
      start_at: "2026-08-09T01:30:00Z",
      end_at: null,
      venue_name: "True Laurel",
      external_url: null,
      travel_buffer_minutes_before: 0,
      address: "753 Alabama St, San Francisco, CA",
      lat: 37.7601,
      lng: -122.4118,
      links: {
        tickets_url: null,
        map_url: "https://www.google.com/maps/search/?api=1&query=37.7601,-122.4118",
        directions_url:
          "https://www.google.com/maps/dir/?api=1&destination=37.7601%2C-122.4118&travelmode=driving",
        food_url: "https://www.google.com/maps/search/restaurants/@37.7601,-122.4118,16z",
        drinks_url: "https://www.google.com/maps/search/bars/@37.7601,-122.4118,16z",
        parking_url: "https://www.google.com/maps/search/parking/@37.7601,-122.4118,16z",
      },
    },
    {
      kind: "main_event",
      event_id: 2,
      title: "Julien Baker at The Chapel",
      start_at: "2026-08-09T03:00:00Z",
      end_at: null,
      venue_name: "The Chapel",
      external_url: "https://tickets.example/julien-baker",
      travel_buffer_minutes_before: 30,
      leave_by: "2026-08-09T02:30:00Z",
      address: "777 Valencia St, San Francisco, CA",
      lat: 37.7599,
      lng: -122.4214,
      links: {
        tickets_url: "https://tickets.example/julien-baker",
        map_url: "https://www.google.com/maps/search/?api=1&query=37.7599,-122.4214",
        directions_url:
          "https://www.google.com/maps/dir/?api=1&destination=37.7599%2C-122.4214&travelmode=driving&origin=37.7601%2C-122.4118",
        food_url: "https://www.google.com/maps/search/restaurants/@37.7599,-122.4214,16z",
        drinks_url: "https://www.google.com/maps/search/bars/@37.7599,-122.4214,16z",
        parking_url: "https://www.google.com/maps/search/parking/@37.7599,-122.4214,16z",
      },
    },
  ],
  text: "Date night in Mission — Sat, Aug 8\n\n1. 6:30 PM · Before\n   Happy hour at True Laurel",
};

test("shared itinerary renders every stop with its map links", async ({ page }) => {
  await page.route(`${API_BASE}/shared/itineraries/*`, (route) =>
    route.fulfill({ json: SHARED_ITINERARY })
  );

  await page.goto(`/itinerary/${SHARED_ITINERARY.share_token}`);

  await expect(
    page.getByRole("heading", { name: /Date night in Mission/i })
  ).toBeVisible();

  await expect(page.getByText(SHARED_ITINERARY.query, { exact: true })).toHaveCount(0);
  await expect(page.getByText(/Public link expires/)).toBeVisible();

  const stops = page.getByRole("listitem");
  await expect(stops).toHaveCount(2);

  await expect(page.getByText("Julien Baker at The Chapel")).toBeVisible();
  await expect(page.getByText(/777 Valencia St/)).toBeVisible();
  await expect(page.getByText(/Leave by ~7:30 PM/i)).toBeVisible();

  // Directions and parking are the links you need while standing outside.
  const secondStop = stops.nth(1);
  await expect(secondStop.getByRole("link", { name: "Directions" })).toHaveAttribute(
    "href",
    /maps\/dir/
  );
  await expect(secondStop.getByRole("link", { name: "Parking" })).toHaveAttribute(
    "href",
    /maps\/search\/parking/
  );
  await expect(secondStop.getByRole("link", { name: "Food nearby" })).toBeVisible();
  await expect(secondStop.getByRole("link", { name: "Drinks nearby" })).toBeVisible();
  await expect(secondStop.getByRole("link", { name: "Tickets" })).toHaveAttribute(
    "href",
    "https://tickets.example/julien-baker"
  );

  // The first stop has no ticket link and should not invent one.
  await expect(stops.nth(0).getByRole("link", { name: "Tickets" })).toHaveCount(0);
});

async function signIn(page: Page) {
  await page.addInitScript(() => {
    localStorage.setItem("tof_auth", JSON.stringify({ token: "owner-token", email: "owner@example.test", userId: 7 }));
  });
}

async function buildPlan(page: Page) {
  await page.route(`${API_BASE}/concierge/itinerary`, (route) => route.fulfill({ json: SHARED_ITINERARY }));
  await page.goto("/planner");
  const input = page.getByPlaceholder(/plan a date in the Mission/);
  await input.fill("Private anniversary request, do not publish");
  await page.getByRole("button", { name: "Build itinerary", exact: true }).click();
  await expect(page.getByText("Julien Baker at The Chapel")).toBeVisible();
}

test("building stays private until explicit publishing, which omits the prompt and uses selected expiry", async ({ page }) => {
  await signIn(page);
  const posted: Record<string, unknown>[] = [];
  await page.route(`${API_BASE}/concierge/itinerary/share`, (route) => {
    posted.push(route.request().postDataJSON());
    expect(route.request().headers().authorization).toBe("Bearer owner-token");
    return route.fulfill({ json: SHARED_ITINERARY });
  });
  await buildPlan(page);
  expect(posted).toHaveLength(0);
  await expect(page.getByText(/Anyone with the link can read this event plan/)).toBeVisible();
  await expect(page.getByText(/Your original request stays private and is not included/)).toBeVisible();
  await expect(page.getByLabel("Public link expires after")).toHaveValue("14");
  await page.getByPlaceholder(/plan a date in the Mission/).fill("A different private Sunday request");
  await page.getByLabel("Public link expires after").selectOption("7");
  await page.getByRole("button", { name: "Create public link", exact: true }).click();
  await expect(page.getByRole("button", { name: "Public link created", exact: true })).toBeDisabled();
  expect(posted).toHaveLength(1);
  expect(posted[0]).not.toHaveProperty("query");
  expect(posted[0].expires_in_days).toBe(7);
  expect(JSON.stringify(posted[0])).not.toContain("private");
  await expect(page.getByRole("link", { name: "Manage or revoke shared plans" })).toHaveAttribute("href", "/shared-plans");
  await expect(page.getByText(/Expires .*Pacific time/)).toBeVisible();
});

test("anonymous planning can copy text and explains sign-in before public sharing", async ({ page }) => {
  await page.addInitScript(() => {
    Object.defineProperty(navigator, "clipboard", { value: { writeText: async () => undefined } });
  });
  let shared = false;
  await page.route(`${API_BASE}/concierge/itinerary/share`, (route) => {
    shared = true;
    return route.fulfill({ json: SHARED_ITINERARY });
  });
  await buildPlan(page);
  await expect(page.getByRole("button", { name: "Create public link", exact: true })).toHaveCount(0);
  await expect(page.getByText(/Sign in to create a public link/)).toBeVisible();
  await expect(page.getByText(/Copy it before leaving this page to sign in; this draft is not saved/)).toBeVisible();
  await page.getByRole("button", { name: "Copy as text" }).click();
  await expect(page.getByRole("button", { name: "Copied", exact: true })).toBeVisible();
  expect(shared).toBe(false);
  await expect(page).toHaveURL(/\/planner$/);
});

test("logging out clears the private planner draft and newly created link", async ({ page }) => {
  await signIn(page);
  await page.route(`${API_BASE}/concierge/itinerary/share`, (route) => route.fulfill({ json: SHARED_ITINERARY }));
  await buildPlan(page);
  await page.getByRole("button", { name: "Create public link", exact: true }).click();
  await expect(page.getByRole("button", { name: "Public link created", exact: true })).toBeVisible();
  await page.getByRole("button", { name: "Log out" }).click();
  await expect(page.getByText("Julien Baker at The Chapel")).toHaveCount(0);
  await expect(page.getByPlaceholder(/plan a date in the Mission/)).toHaveValue("");
  await expect(page.getByRole("button", { name: "Copy link" })).toHaveCount(0);
});

test.describe("opened from another timezone", () => {
  // A shared plan travels; the venue's clock does not. Someone reading this in
  // New York still needs the time they should show up at the door in SF.
  test.use({ timezoneId: "America/New_York" });

  test("times stay local to the venue, not the reader", async ({ page }) => {
    await page.route(`${API_BASE}/shared/itineraries/*`, (route) =>
      route.fulfill({ json: SHARED_ITINERARY })
    );

    await page.goto(`/itinerary/${SHARED_ITINERARY.share_token}`);

    // 03:00 UTC Sunday is 8:00 PM Saturday in SF — and 11:00 PM in New York.
    await expect(page.getByText("8:00 PM")).toBeVisible();
    await expect(page.getByText("11:00 PM")).toHaveCount(0);
    await expect(page.getByText("6:30 PM")).toBeVisible();
    await expect(page.getByText(/Sat, Aug 8/).first()).toBeVisible();
  });
});

test("shared itinerary needs no sign-in", async ({ page }) => {
  await page.route(`${API_BASE}/shared/itineraries/*`, (route) =>
    route.fulfill({ json: SHARED_ITINERARY })
  );

  await page.goto(`/itinerary/${SHARED_ITINERARY.share_token}`);

  await expect(page.getByText("Julien Baker at The Chapel")).toBeVisible();
  await expect(page.getByText(/Sign in to get personalized/i)).toHaveCount(0);
});

test("a missing itinerary shows an error rather than an empty page", async ({ page }) => {
  await page.route(`${API_BASE}/shared/itineraries/*`, (route) =>
    route.fulfill({ status: 404, json: { detail: "Itinerary not found" } })
  );

  await page.goto("/itinerary/does-not-exist-000000000000");

  await expect(page.getByText(/Itinerary not found/i)).toBeVisible();
});

test("shared itinerary degrades gracefully when the API is unreachable", async ({
  page,
}) => {
  // No route stub: the backend genuinely is not running in this suite.
  await page.goto("/itinerary/unreachable-00000000000000");

  await expect(page.getByText(/could not be loaded|failed/i)).toBeVisible();
});

test("refocusing a revoked public link clears the old snapshot and can retry", async ({ page }) => {
  let revoked = false;
  await page.route(`${API_BASE}/shared/itineraries/*`, (route) => revoked
    ? route.fulfill({ status: 404, json: { detail: "Itinerary not found" } })
    : route.fulfill({ json: SHARED_ITINERARY }));
  await page.goto(`/itinerary/${SHARED_ITINERARY.share_token}`);
  await expect(page.getByText("Julien Baker at The Chapel")).toBeVisible();
  revoked = true;
  await page.evaluate(() => window.dispatchEvent(new Event("focus")));
  await expect(page.getByText("Itinerary not found", { exact: true })).toBeVisible();
  await expect(page.getByText("Julien Baker at The Chapel")).toHaveCount(0);
  await expect(page.getByRole("button", { name: "Copy as text" })).toHaveCount(0);
  revoked = false;
  await page.getByRole("button", { name: "Retry", exact: true }).click();
  await expect(page.getByText("Julien Baker at The Chapel")).toBeVisible();
});

test("navigating to an unavailable token never retains the previous shared plan", async ({ page }) => {
  await page.route(`${API_BASE}/shared/itineraries/*`, (route) => route.request().url().endsWith(SHARED_ITINERARY.share_token)
    ? route.fulfill({ json: SHARED_ITINERARY })
    : route.fulfill({ status: 404, json: { detail: "Itinerary not found" } }));
  await page.goto(`/itinerary/${SHARED_ITINERARY.share_token}`);
  await expect(page.getByText("Julien Baker at The Chapel")).toBeVisible();
  // Exercise client navigation between two instances of the dynamic route.
  // Next exposes its router for browser tooling; pushState alone only changes
  // the URL and does not resolve a new dynamic parameter.
  await page.evaluate(() => {
    const debug = (window as unknown as { nd: { router: { push: (path: string) => void } } }).nd;
    debug.router.push("/itinerary/revoked-token");
  });
  await expect(page.getByText("Itinerary not found", { exact: true })).toBeVisible();
  await expect(page.getByText("Julien Baker at The Chapel")).toHaveCount(0);
});

test("public snapshot disappears when its expiry is reached", async ({ page }) => {
  const now = new Date("2026-09-29T12:00:00Z");
  await page.clock.install({ time: now });
  let expired = false;
  await page.route(`${API_BASE}/shared/itineraries/*`, (route) => {
    return !expired
      ? route.fulfill({ json: { ...SHARED_ITINERARY, expires_at: new Date(now.getTime() + 60_000).toISOString() } })
      : route.fulfill({ status: 404, json: { detail: "Itinerary not found" } });
  });
  await page.goto(`/itinerary/${SHARED_ITINERARY.share_token}`);
  await expect(page.getByText("Julien Baker at The Chapel")).toBeVisible();
  expired = true;
  await page.clock.fastForward(60_001);
  await expect(page.getByText("Itinerary not found", { exact: true })).toBeVisible();
  await expect(page.getByText("Julien Baker at The Chapel")).toHaveCount(0);
});

test("a 30-day public link does not overflow the browser expiry timer", async ({ page }) => {
  const now = new Date("2026-09-29T12:00:00Z");
  await page.clock.install({ time: now });
  let calls = 0;
  await page.route(`${API_BASE}/shared/itineraries/*`, (route) => {
    calls++;
    return route.fulfill({ json: { ...SHARED_ITINERARY, expires_at: new Date(now.getTime() + 30 * 86_400_000).toISOString() } });
  });
  await page.goto(`/itinerary/${SHARED_ITINERARY.share_token}`);
  await expect(page.getByText("Julien Baker at The Chapel")).toBeVisible();
  const initialCalls = calls;
  await page.clock.fastForward(60_000);
  expect(calls).toBe(initialCalls);
  await expect(page.getByText("Julien Baker at The Chapel")).toBeVisible();
});

const SUMMARY = {
  share_token: SHARED_ITINERARY.share_token,
  share_url: SHARED_ITINERARY.share_url,
  title: SHARED_ITINERARY.title,
  created_at: SHARED_ITINERARY.created_at,
  expires_at: SHARED_ITINERARY.expires_at,
  revoked_at: null as string | null,
  status: "active",
};

test("owners find links after reload, revoke them, and see the persisted outcome", async ({ page }) => {
  await signIn(page);
  let revoked = false;
  await page.route(`${API_BASE}/users/me/itineraries?*`, (route) => {
    expect(route.request().headers().authorization).toBe("Bearer owner-token");
    return route.fulfill({ json: [{ ...SUMMARY, status: revoked ? "revoked" : "active", revoked_at: revoked ? new Date().toISOString() : null }] });
  });
  await page.route(`${API_BASE}/users/me/itineraries/${SUMMARY.share_token}`, (route) => {
    expect(route.request().method()).toBe("DELETE");
    revoked = true;
    return route.fulfill({ status: 204 });
  });
  await page.goto("/shared-plans");
  await expect(page.getByRole("link", { name: SUMMARY.title, exact: true })).toBeVisible();
  await page.reload();
  await expect(page.getByRole("link", { name: SUMMARY.title, exact: true })).toBeVisible();
  await page.getByRole("button", { name: "Revoke link", exact: true }).click();
  await expect(page.getByText("Revoked", { exact: true })).toBeVisible();
  await expect(page.getByRole("status")).toContainText("Link revoked");
  await expect(page.getByRole("button", { name: "Copy link", exact: true })).toHaveCount(0);
  await page.reload();
  await expect(page.getByText("Revoked", { exact: true })).toBeVisible();
  await expect(page.getByRole("button", { name: "Revoke link", exact: true })).toHaveCount(0);
});

test("owner revoke failure leaves the link active and can be retried", async ({ page }) => {
  await signIn(page);
  let deletes = 0;
  await page.route(`${API_BASE}/users/me/itineraries?*`, (route) => route.fulfill({ json: [SUMMARY] }));
  await page.route(`${API_BASE}/users/me/itineraries/${SUMMARY.share_token}`, (route) => {
    deletes++;
    return deletes === 1
      ? route.fulfill({ status: 503, json: { detail: "Please try again" } })
      : route.fulfill({ status: 204 });
  });
  await page.goto("/shared-plans");
  await page.getByRole("button", { name: "Revoke link", exact: true }).click();
  await expect(page.getByText(/Please try again/)).toBeVisible();
  await expect(page.getByText("Active", { exact: true })).toBeVisible();
  expect(deletes).toBe(1);
  await page.getByRole("button", { name: "Revoke link", exact: true }).click();
  await expect(page.getByText("Revoked", { exact: true })).toBeVisible();
});

test("logging out clears the owner's links and stops authenticated list reads", async ({ page }) => {
  await signIn(page);
  let calls = 0;
  await page.route(`${API_BASE}/users/me/itineraries?*`, (route) => {
    calls++;
    return route.fulfill({ json: [SUMMARY] });
  });
  await page.goto("/shared-plans");
  await expect(page.getByRole("link", { name: SUMMARY.title, exact: true })).toBeVisible();
  await page.getByRole("button", { name: "Log out", exact: true }).click();
  await expect(page.getByRole("link", { name: SUMMARY.title, exact: true })).toHaveCount(0);
  await expect(page.getByText(/Sign in to find and revoke your public links/)).toBeVisible();
  const loggedOutCalls = calls;
  await page.evaluate(() => window.dispatchEvent(new Event("focus")));
  expect(calls).toBe(loggedOutCalls);
});

test("owner links change from active to expired while the page stays open", async ({ page }) => {
  await signIn(page);
  const now = new Date("2026-09-29T12:00:00Z");
  await page.clock.install({ time: now });
  let listCalls = 0;
  await page.route(`${API_BASE}/users/me/itineraries?*`, (route) => {
    listCalls++;
    return route.fulfill({ json: [{ ...SUMMARY, expires_at: new Date(now.getTime() + 60_000).toISOString() }] });
  });
  await page.goto("/shared-plans");
  await expect(page.getByText("Active", { exact: true })).toBeVisible();
  const initialCalls = listCalls;
  await page.clock.fastForward(60_001);
  await expect(page.getByText("Expired", { exact: true })).toBeVisible();
  await expect(page.getByRole("button", { name: "Copy link", exact: true })).toHaveCount(0);
  await expect(page.getByRole("link", { name: SUMMARY.title, exact: true })).toHaveCount(0);
  expect(listCalls).toBe(initialCalls);
});
