import { test, expect } from "@playwright/test";
import { SSR_PLAN, SSR_PLAN_TOKEN } from "../support/fixtures.mjs";
import {
  API, eventFixture, mockExploreApi, signInFixture, stubRemoteImages, trackCspViolations,
} from "./helpers";

// The Content-Security-Policy in next.config.ts has to allow everything the
// app really does (Next's inline bootstrap, Leaflet, CARTO tiles, hotlinked
// https event images, API calls) and nothing has to be loosened by accident.
// Any blocked resource fires a `securitypolicyviolation` event and a console
// error; both are collected and must stay empty.

test("no CSP violations on the public pages, the map view, or an event page", async ({ page }) => {
  const violations = await trackCspViolations(page);
  await stubRemoteImages(page);
  await mockExploreApi(page, {
    events: () => [
      eventFixture(1, { title: "Mapped show", lat: 37.8087, lng: -122.2703, image_url: "https://images.example/a.jpg", city: "Oakland" }),
      eventFixture(2, { title: "Other show", lat: 37.77, lng: -122.42, image_url: "https://images.example/b.jpg" }),
    ],
  });
  await page.route(`${API}/shared/itineraries/*`, (route) => route.fulfill({ json: SSR_PLAN }));

  await page.goto("/");
  await expect(page.getByRole("heading", { level: 1 })).toBeVisible();

  await page.goto("/explore");
  await expect(page.getByRole("heading", { name: "Mapped show" })).toBeVisible();
  await expect(page.locator('img[src="https://images.example/a.jpg"]')).toBeVisible();
  // The hotlinked image actually loaded (it was not blocked by img-src).
  expect(await page.locator('img[src="https://images.example/a.jpg"]').evaluate((img: HTMLImageElement) => img.naturalWidth)).toBeGreaterThan(0);

  // Map view: Leaflet, its styles, markers and CARTO tiles.
  await page.getByRole("button", { name: "Map", exact: true }).click();
  await expect(page.locator(".tof-marker-pin")).toHaveCount(2);
  const tile = page.locator("img.leaflet-tile").first();
  await expect(tile).toHaveAttribute("src", /^https:\/\/[a-d]\.basemaps\.cartocdn\.com\/dark_all\//);
  await expect.poll(() => tile.evaluate((img: HTMLImageElement) => img.complete && img.naturalWidth > 0)).toBe(true);
  await page.locator(".tof-marker-pin").first().click();
  await expect(page.locator(".tof-popup")).toHaveCount(1);
  await expect(page.locator(".tof-popup")).toBeVisible();

  // Server-rendered event page with inline JSON-LD and a third-party image.
  await page.goto("/events/101");
  await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
  await expect(page.locator('script[type="application/ld+json"]')).toHaveCount(1);
  await expect(page.locator("main img")).toBeVisible();

  for (const path of ["/planner", "/login", "/forgot-password", "/reset-password?token=t", "/privacy", "/terms", `/itinerary/${SSR_PLAN_TOKEN}`, "/definitely-missing"]) {
    await page.goto(path);
    await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
  }

  expect(await violations()).toEqual([]);
});

test("no CSP violations on signed-in pages, including the data download", async ({ page }) => {
  const violations = await trackCspViolations(page);
  await signInFixture(page);
  await page.route(`${API}/**`, (route) => {
    const path = new URL(route.request().url()).pathname;
    if (path === "/users/me") return route.fulfill({ json: { user_id: 1, preferred_vibes: [], saved_event_ids: [], vibe_scores: {} } });
    if (path === "/users/me/export") return route.fulfill({ json: { account: {} } });
    return route.fulfill({ json: [] });
  });
  for (const path of ["/account", "/recommendations", "/folders", "/shared-plans"]) {
    await page.goto(path);
    await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
  }
  await page.goto("/account");
  const [download] = await Promise.all([
    page.waitForEvent("download"),
    page.getByRole("button", { name: "Download my data" }).click(),
  ]);
  expect(download.suggestedFilename()).toMatch(/\.json$/);
  expect(await violations()).toEqual([]);
});

test("the violation tracker itself works: a disallowed request is caught", async ({ page }) => {
  const violations = await trackCspViolations(page);
  await page.goto("/privacy");
  await page.evaluate(() => fetch("https://not-allowed.example/collect").catch(() => undefined));
  await expect.poll(async () => (await violations()).join("\n")).toContain("connect-src");
});
