import { test, expect } from "@playwright/test";
import { eventFixture, mockExploreApi } from "./helpers";

test.describe("near me with location allowed", () => {
  test.use({ geolocation: { latitude: 37.80441, longitude: -122.27114 }, permissions: ["geolocation"] });

  test("sends position, radius and distance sort; shows distance; a region turns it off", async ({ page }) => {
    const api = await mockExploreApi(page, {
      events: (params) => params.has("lat")
        ? [
          eventFixture(1, { title: "Around the corner", distance_miles: 0.42 }),
          eventFixture(2, { title: "Across town", distance_miles: 12.3 }),
        ]
        : [eventFixture(3, { title: "Anywhere event" })],
    });
    await page.goto("/explore?region=sf");
    await expect(page.getByRole("heading", { name: "Anywhere event" })).toBeVisible();

    const nearMe = page.getByRole("button", { name: "Near me", exact: true });
    await nearMe.click();
    await expect(nearMe).toHaveAttribute("aria-pressed", "true");
    // Position is rounded (about 100 m), the default radius is 5 miles, and
    // distance replaces the region filter.
    await expect.poll(api.last).toEqual({
      lat: "37.804", lng: "-122.271", radius_miles: "5", sort_by: "distance", limit: "20", offset: "0",
    });
    // Coordinates never go into the shareable URL.
    await expect(page).toHaveURL(/\/explore$/);
    await expect(page.getByRole("button", { name: /^San Francisco/ })).toHaveAttribute("aria-pressed", "false");

    await expect(page.getByRole("article").filter({ hasText: "Around the corner" })).toContainText("0.4 mi away");
    await expect(page.getByRole("article").filter({ hasText: "Across town" })).toContainText("12 mi away");

    const radius = page.getByRole("combobox", { name: "Within" });
    await expect(radius.locator("option")).toHaveText(["1 mile", "3 miles", "5 miles", "10 miles"]);
    await radius.selectOption("10");
    await expect.poll(api.last).toMatchObject({ radius_miles: "10", sort_by: "distance" });
    await radius.selectOption("1");
    await expect.poll(api.last).toMatchObject({ radius_miles: "1" });

    // Other filters combine with it.
    await page.getByRole("button", { name: "Free", exact: true }).click();
    await expect.poll(api.last).toMatchObject({ is_free: "true", lat: "37.804", radius_miles: "1" });

    // Choosing a region switches back to region filtering.
    await page.getByRole("button", { name: /^East Bay/ }).click();
    await expect(nearMe).toHaveAttribute("aria-pressed", "false");
    await expect.poll(api.last).toEqual({ is_free: "true", region: "east_bay", limit: "20", offset: "0" });
    await expect(page.getByRole("combobox", { name: "Within" })).toHaveCount(0);
  });

  test("an empty radius says so and suggests widening it", async ({ page }) => {
    await mockExploreApi(page, { events: (params) => (params.has("lat") ? [] : [eventFixture(1)]) });
    await page.goto("/explore");
    await page.getByRole("button", { name: "Near me", exact: true }).click();
    await expect(page.getByText("No events found within 5 miles of you. Try a wider radius.")).toBeVisible();
  });
});

for (const [name, code, message] of [
  ["denied", 1, /Location access is blocked/],
  ["unavailable", 2, /couldn't determine your location/],
] as const) {
  test(`near me explains a ${name} location and keeps showing results`, async ({ page }) => {
    await page.addInitScript((errorCode) => {
      Object.defineProperty(navigator, "geolocation", {
        configurable: true,
        value: {
          getCurrentPosition: (_ok: unknown, fail: (error: unknown) => void) =>
            setTimeout(() => fail({ code: errorCode, PERMISSION_DENIED: 1, POSITION_UNAVAILABLE: 2, TIMEOUT: 3 }), 10),
        },
      });
    }, code);
    const api = await mockExploreApi(page);
    await page.goto("/explore");
    await expect(page.getByRole("heading", { name: "Event 1" })).toBeVisible();
    const nearMe = page.getByRole("button", { name: "Near me", exact: true });
    await nearMe.click();
    await expect(page.getByRole("main").getByRole("alert").filter({ hasText: message })).toBeVisible();
    await expect(nearMe).toHaveAttribute("aria-pressed", "false");
    await expect(page.getByRole("heading", { name: "Event 1" })).toBeVisible();
    expect(api.queries.some((query) => query.has("lat"))).toBe(false);
  });
}

test("near me reports a real browser refusal (no permission granted)", async ({ page }) => {
  await mockExploreApi(page);
  await page.goto("/explore");
  await page.getByRole("button", { name: "Near me", exact: true }).click();
  await expect(page.getByRole("main").getByRole("alert").filter({ hasText: /Location access is blocked|couldn't determine your location/ })).toBeVisible({ timeout: 15_000 });
});
