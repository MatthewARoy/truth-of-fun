import { test, expect } from "@playwright/test";

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

  const stops = page.getByRole("listitem");
  await expect(stops).toHaveCount(2);

  await expect(page.getByText("Julien Baker at The Chapel")).toBeVisible();
  await expect(page.getByText(/777 Valencia St/)).toBeVisible();
  await expect(page.getByText(/leave ~30 min ahead/i)).toBeVisible();

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
