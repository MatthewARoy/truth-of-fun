import { test, expect } from "@playwright/test";
import { localDayRange, startOfLocalDay } from "../../lib/localtime";
import { exploreSearch, parseExploreParams } from "../../lib/explore-params";
import { API, eventFixture, mockExploreApi, stubRemoteImages } from "./helpers";

test("Pacific day boundaries are correct in winter, summer and across both DST changes", () => {
  expect(localDayRange("2026-12-05")).toEqual({
    start_at: "2026-12-05T08:00:00.000Z", end_at: "2026-12-06T07:59:59.999Z",
  });
  expect(localDayRange("2030-07-04", "2030-07-06")).toEqual({
    start_at: "2030-07-04T07:00:00.000Z", end_at: "2030-07-07T06:59:59.999Z",
  });
  // Spring forward: a 23-hour day. Fall back: a 25-hour day.
  expect(localDayRange("2026-03-08")).toEqual({
    start_at: "2026-03-08T08:00:00.000Z", end_at: "2026-03-09T06:59:59.999Z",
  });
  expect(localDayRange("2026-11-01")).toEqual({
    start_at: "2026-11-01T07:00:00.000Z", end_at: "2026-11-02T07:59:59.999Z",
  });
  expect(startOfLocalDay("2026-03-09").toISOString()).toBe("2026-03-09T07:00:00.000Z");
  // A reversed range collapses to the first day rather than producing an empty window.
  expect(localDayRange("2026-12-05", "2026-12-01")).toEqual(localDayRange("2026-12-05"));
});

test("explore query strings round-trip and drop anything invalid", () => {
  const filters = parseExploreParams(new URLSearchParams(
    "q=+jazz+&when=tonight&region=east_bay&city=Oakland&category=Music&free=1&view=map"
  ));
  expect(filters).toEqual({
    q: "jazz", when: "tonight", date: "", to: "", region: "east_bay", city: "Oakland",
    category: "Music", free: true, view: "map",
  });
  expect(exploreSearch(filters)).toBe("?q=jazz&when=tonight&region=east_bay&city=Oakland&category=Music&free=1&view=map");
  // Dates win over presets; a city without a region, bad regions and bad dates are ignored.
  expect(parseExploreParams(new URLSearchParams("when=tonight&date=2030-07-04&to=2030-07-01&city=Oakland&region=mars&free=yes&view=grid")))
    .toMatchObject({ when: "", date: "2030-07-04", to: "", region: "", city: "", free: false, view: "list" });
  expect(parseExploreParams(new URLSearchParams("date=2030-02-31&when=this_weekend")))
    .toMatchObject({ date: "", when: "this_weekend" });
  expect(exploreSearch(parseExploreParams(new URLSearchParams("")))).toBe("");
});

test.describe("explore filters", () => {
  // The reader's own timezone must not move a Pacific-time date filter.
  test.use({ timezoneId: "Asia/Tokyo" });

  test("region, city, free, dates, category, search and view are sent to the API and kept in the URL", async ({ page }) => {
    const api = await mockExploreApi(page);
    await page.goto("/explore");
    await expect(page.getByRole("heading", { name: "Event 1" })).toBeVisible();
    expect(api.last()).toEqual({ limit: "20", offset: "0" });

    // Region chips come from GET /regions, with counts.
    const eastBay = page.getByRole("button", { name: "East Bay, 412 upcoming events" });
    await expect(eastBay).toHaveAttribute("aria-pressed", "false");
    await eastBay.click();
    await expect(page).toHaveURL(/\/explore\?region=east_bay$/);
    await expect(eastBay).toHaveAttribute("aria-pressed", "true");
    await expect.poll(api.last).toEqual({ region: "east_bay", limit: "20", offset: "0" });

    // The city selector lists that region's cities.
    const city = page.getByRole("combobox", { name: "City in East Bay" });
    await expect(city.locator("option")).toHaveText(["All of East Bay", "Oakland (230)", "Berkeley (120)"]);
    await city.selectOption("Oakland");
    await expect(page).toHaveURL(/region=east_bay&city=Oakland$/);
    await expect.poll(api.last).toMatchObject({ region: "east_bay", city: "Oakland" });

    const free = page.getByRole("button", { name: "Free", exact: true });
    await free.click();
    await expect(free).toHaveAttribute("aria-pressed", "true");
    await expect(page).toHaveURL(/free=1/);
    await expect.poll(api.last).toMatchObject({ is_free: "true", city: "Oakland" });

    // A single day, then a range. Boundaries are Pacific midnight, not Tokyo's.
    await page.getByRole("button", { name: "Pick dates" }).click();
    await page.getByRole("main").getByLabel("Date", { exact: true }).fill("2030-07-04");
    await expect(page).toHaveURL(/date=2030-07-04/);
    await expect.poll(api.last).toMatchObject({
      start_at: "2030-07-04T07:00:00.000Z", end_at: "2030-07-05T06:59:59.999Z",
    });
    expect(api.last()).not.toHaveProperty("time_preset");
    await page.getByRole("main").getByLabel("Through (optional)").fill("2030-07-06");
    await expect(page).toHaveURL(/date=2030-07-04&to=2030-07-06/);
    await expect.poll(api.last).toMatchObject({
      start_at: "2030-07-04T07:00:00.000Z", end_at: "2030-07-07T06:59:59.999Z",
    });
    await expect(page.getByRole("button", { name: "Thu, Jul 4 – Sat, Jul 6" })).toHaveAttribute("aria-pressed", "true");

    // The shortcuts still exist and replace a custom range.
    await page.getByRole("button", { name: "This weekend", exact: true }).click();
    await expect(page).toHaveURL(/when=this_weekend/);
    await expect(page).not.toHaveURL(/date=/);
    await expect.poll(api.last).toMatchObject({ time_preset: "this_weekend" });
    expect(api.last()).not.toHaveProperty("start_at");
    await page.getByRole("button", { name: "Tonight", exact: true }).click();
    await expect.poll(api.last).toMatchObject({ time_preset: "tonight" });

    await page.getByRole("button", { name: "Comedy", exact: true }).click();
    await expect.poll(api.last).toMatchObject({ category: "Comedy" });

    await page.getByRole("searchbox", { name: "Search events" }).fill("jazz");
    await page.getByRole("button", { name: "Search", exact: true }).click();
    await expect.poll(api.last).toEqual({
      q: "jazz", category: "Comedy", is_free: "true", time_preset: "tonight",
      region: "east_bay", city: "Oakland", limit: "20", offset: "0",
    });
    await expect(page).toHaveURL(
      /\/explore\?q=jazz&when=tonight&region=east_bay&city=Oakland&category=Comedy&free=1$/
    );

    await page.getByRole("button", { name: "Map", exact: true }).click();
    await expect(page).toHaveURL(/&view=map$/);

    // The web app never sends the retired keyword preset.
    expect(api.queries.some((query) => query.has("location_preset"))).toBe(false);

    // Refresh: everything is restored from the URL alone.
    await page.reload();
    await expect(page.getByRole("searchbox", { name: "Search events" })).toHaveValue("jazz");
    await expect(page.getByRole("button", { name: "Tonight", exact: true })).toHaveAttribute("aria-pressed", "true");
    await expect(page.getByRole("button", { name: /^East Bay/ })).toHaveAttribute("aria-pressed", "true");
    await expect(page.getByRole("combobox", { name: "City in East Bay" })).toHaveValue("Oakland");
    await expect(page.getByRole("button", { name: "Comedy", exact: true })).toHaveAttribute("aria-pressed", "true");
    await expect(page.getByRole("button", { name: "Free", exact: true })).toHaveAttribute("aria-pressed", "true");
    await expect(page.getByRole("button", { name: "Map", exact: true })).toHaveAttribute("aria-pressed", "true");
    await expect(page.getByRole("application", { name: /Event venue map/i })).toBeVisible();
    await expect.poll(api.last).toMatchObject({ q: "jazz", region: "east_bay", city: "Oakland", is_free: "true" });

    // Back and forward walk the filter history.
    await page.goBack();
    await expect(page).not.toHaveURL(/view=map/);
    await expect(page.getByRole("button", { name: "List", exact: true })).toHaveAttribute("aria-pressed", "true");
    await page.goBack();
    await expect(page).not.toHaveURL(/q=jazz/);
    await expect(page.getByRole("searchbox", { name: "Search events" })).toHaveValue("");
    await expect.poll(api.last).not.toHaveProperty("q");
    await page.goForward();
    await expect(page).toHaveURL(/q=jazz/);
    await expect(page.getByRole("searchbox", { name: "Search events" })).toHaveValue("jazz");
    await expect.poll(api.last).toMatchObject({ q: "jazz" });

    // Clearing keeps nothing behind. (Let the router finish restoring the
    // history entry first: a click in the same instant as a back/forward
    // traversal can be overtaken by it.)
    await page.waitForLoadState("networkidle");
    await page.getByRole("button", { name: "Clear filters" }).click();
    await expect(page).toHaveURL(/\/explore$/);
    await expect.poll(api.last).toEqual({ limit: "20", offset: "0" });
  });

  test("a shared search link applies its filters on first load; junk parameters are ignored", async ({ page }) => {
    const api = await mockExploreApi(page);
    await page.goto("/explore?q=jazz&date=2030-07-04&region=east_bay&city=Oakland&category=Music&free=1");
    await expect(page.getByRole("heading", { name: "Event 1" })).toBeVisible();
    expect(Object.fromEntries(api.queries[0])).toEqual({
      q: "jazz", category: "Music", is_free: "true",
      start_at: "2030-07-04T07:00:00.000Z", end_at: "2030-07-05T06:59:59.999Z",
      region: "east_bay", city: "Oakland", limit: "20", offset: "0",
    });
    await expect(page.getByRole("main").getByLabel("Date", { exact: true })).toHaveValue("2030-07-04");

    await page.goto("/explore?region=mars&date=nope&when=tonight&city=Oakland&free=true");
    await expect(page.getByRole("heading", { name: "Event 1" })).toBeVisible();
    await expect.poll(api.last).toEqual({ time_preset: "tonight", limit: "20", offset: "0" });
    await expect(page.getByRole("button", { name: "Anywhere", exact: true })).toHaveAttribute("aria-pressed", "true");
  });

  test("region chips still filter when GET /regions fails", async ({ page }) => {
    const api = await mockExploreApi(page, {
      regions: (route) => route.fulfill({ status: 500, json: { detail: "boom" } }),
    });
    await page.goto("/explore?region=east_bay&city=Oakland");
    // Static labels, no counts, and the applied city stays selectable.
    for (const name of ["San Francisco", "East Bay", "Peninsula", "South Bay", "North Bay"]) {
      await expect(page.getByRole("button", { name, exact: true })).toBeVisible();
    }
    await expect(page.getByRole("combobox", { name: /^City in/ })).toHaveValue("Oakland");
    await expect.poll(api.last).toMatchObject({ region: "east_bay", city: "Oakland" });
    await page.getByRole("button", { name: "South Bay", exact: true }).click();
    await expect(page).toHaveURL(/\/explore\?region=south_bay$/);
    await expect.poll(api.last).toEqual({ region: "south_bay", limit: "20", offset: "0" });
    await expect(page.getByRole("combobox", { name: /^City in/ })).toHaveCount(0);
  });

  test("an unknown city reported by the API is shown as an error, not as zero results", async ({ page }) => {
    await page.route(`${API}/regions`, (route) => route.fulfill({ json: { regions: [] } }));
    await page.route((url) => url.href.startsWith(`${API}/events?`), (route) =>
      route.fulfill({ status: 400, json: { detail: "Unknown city. See GET /regions for the cities that can be filtered." } })
    );
    await page.goto("/explore?region=east_bay&city=Atlantis");
    await expect(page.getByRole("main").getByRole("alert")).toContainText("Unknown city");
    await expect(page.getByText(/No events found/)).toHaveCount(0);
  });
});

test("cards show price, city and distance-free facts, expand descriptions, and only render safe links and images", async ({ page }) => {
  const long = `${"Doors at seven. ".repeat(20)}The very last sentence.`;
  await stubRemoteImages(page);
  await mockExploreApi(page, {
    events: () => [
      eventFixture(1, {
        title: "Paid show", price: 45, currency: "USD", city: "Oakland", venue_name: "Fox Theater",
        description: long, image_url: "https://images.example/poster.jpg",
        external_url: "https://tickets.example/paid",
      }),
      eventFixture(2, {
        title: "Free show", is_free: true, price: null, city: "Berkeley", venue_name: "Freight & Salvage",
        description: "Short.", image_url: "http://insecure.example/poster.jpg",
        external_url: "javascript:alert(document.domain)",
      }),
      eventFixture(3, {
        title: "Unpriced show", price: null, is_free: false, description: null,
        image_url: "data:image/png;base64,AAAA", venue_name: "San Jose Civic", city: "San Jose",
      }),
    ],
  });
  await page.goto("/explore");
  const card = (title: string) => page.getByRole("article").filter({ hasText: title });

  const paid = card("Paid show");
  await expect(paid).toContainText("$45");
  await expect(paid).toContainText("Fox Theater · Oakland");
  await expect(paid.getByRole("link", { name: "Paid show", exact: true })).toHaveAttribute("href", "/events/1");
  const tickets = paid.getByRole("link", { name: "Tickets" });
  await expect(tickets).toHaveAttribute("href", "https://tickets.example/paid");
  await expect(tickets).toHaveAttribute("rel", /noopener/);

  // Expandable description.
  await expect(paid.getByText("The very last sentence.")).toBeVisible();
  const description = paid.locator("p", { hasText: "The very last sentence." });
  const collapsed = (await description.boundingBox())!.height;
  const toggle = paid.getByRole("button", { name: "Show more" });
  await expect(toggle).toHaveAttribute("aria-expanded", "false");
  await toggle.click();
  await expect(paid.getByRole("button", { name: "Show less" })).toHaveAttribute("aria-expanded", "true");
  expect((await description.boundingBox())!.height).toBeGreaterThan(collapsed);

  // Hotlinked https image: lazy, no referrer.
  const image = page.locator('img[src="https://images.example/poster.jpg"]');
  await expect(image).toHaveAttribute("referrerpolicy", "no-referrer");
  await expect(image).toHaveAttribute("loading", "lazy");

  const free = card("Free show");
  await expect(free).toContainText("Free");
  await expect(free).toContainText("Freight & Salvage · Berkeley");
  await expect(free.getByRole("button", { name: /Show (more|less)/ })).toHaveCount(0);
  // A javascript: URL from a scraped listing never becomes a link; http and data images never render.
  await expect(free.getByRole("link", { name: "Tickets" })).toHaveCount(0);
  await expect(page.locator('a[href^="javascript:"]')).toHaveCount(0);
  await expect(page.locator("main img")).toHaveCount(1);

  // No price is not "Free", and nothing is invented.
  const unpriced = card("Unpriced show");
  await expect(unpriced).not.toContainText("Free");
  await expect(unpriced).not.toContainText("$");
  // A venue that already names its city is not followed by the city again.
  await expect(unpriced).toContainText("San Jose Civic");
  await expect(unpriced).not.toContainText("San Jose Civic · San Jose");

  await expect(page.getByRole("button", { name: "Mark viewed" })).toHaveCount(0);
});

test("a hotlinked image that fails to load disappears instead of leaving a broken frame", async ({ page }) => {
  await page.route(/^https:\/\/images\.example\//, (route) => route.abort());
  await mockExploreApi(page, {
    events: () => [eventFixture(1, { title: "Broken poster", image_url: "https://images.example/missing.jpg" })],
  });
  await page.goto("/explore");
  await expect(page.getByRole("heading", { name: "Broken poster" })).toBeVisible();
  await expect(page.locator("main img")).toHaveCount(0);
});

test("the map leaves out approximate locations, says how many, and popups carry the time and a link", async ({ page }) => {
  await stubRemoteImages(page);
  await mockExploreApi(page, {
    events: () => [
      eventFixture(1, { title: "Pinned <b>show</b>", lat: 37.8087, lng: -122.2703, location_confidence: 0.9, venue_name: "Fox Theater", city: "Oakland" }),
      eventFixture(2, { title: "Centroid one", lat: 37.7749, lng: -122.4194, location_confidence: 0.2 }),
      eventFixture(3, { title: "Centroid two", lat: 37.7749, lng: -122.4194, location_confidence: 0.49 }),
      eventFixture(4, { title: "Nowhere", lat: null, lng: null }),
    ],
  });
  await page.goto("/explore?view=map");
  await expect(page.locator(".tof-marker-pin")).toHaveCount(1);
  await expect(page.getByTestId("map-summary")).toHaveText(
    "Showing 1 of 4 loaded events on the map. 2 events are not shown on the map because their location is only approximate. "
    + "1 event has no location to plot. Switch to the list to see them."
  );
  await page.locator(".tof-marker-pin").click();
  const popup = page.locator(".tof-popup");
  await expect(popup).toHaveCount(1);
  // Title is escaped text, not markup.
  await expect(popup.locator("strong")).toHaveText("Pinned <b>show</b>");
  await expect(popup.locator("b")).toHaveCount(0);
  await expect(popup).toContainText("Thu, Jul 4 · 8:00 PM");
  await expect(popup).toContainText("Fox Theater · Oakland");
  await expect(popup.getByRole("link", { name: "View event details" })).toHaveAttribute("href", "/events/1");
});
