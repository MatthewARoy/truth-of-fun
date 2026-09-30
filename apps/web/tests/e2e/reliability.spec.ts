import { test, expect, type Page } from "@playwright/test";
import { safeReturnPath } from "../../lib/return-path";

const API = process.env.NEXT_PUBLIC_API_BASE_URL || "http://127.0.0.1:8000";
const event = (id: number, title = `Event ${id}`) => ({
  id, title, description: "An event", start_at: "2026-10-04T06:00:00Z",
  start_time_is_estimated: false, end_at: null, external_url: null,
  venue_name: "SF Venue", tags: [], categories: [], image_url: null,
  price: null, currency: null, status: "scheduled", people_interested: 0,
});
const folder = { id: 7, name: "Private Saturday plans", share_token: "private-share", items: [] };

async function signInFixture(page: Page) {
  await page.addInitScript(() => {
    localStorage.setItem("tof_auth", JSON.stringify({ token: "fixture-token", email: "me@example.test", userId: 1 }));
  });
}

test("post-login destinations accept local paths and reject unsafe URLs", () => {
  expect(safeReturnPath("/invites/abc?from=friend#details")).toBe("/invites/abc?from=friend#details");
  for (const unsafe of [null, "https://evil.example", "//evil.example", "/\\evil.example", "javascript:alert(1)", "/\nevil.example", "/login"]) {
    expect(safeReturnPath(unsafe)).toBe("/explore");
  }
});

test("failed pagination retries the same offset and ignores unsubmitted search text", async ({ page }) => {
  const queries: URLSearchParams[] = [];
  let failed = false;
  await page.route(`${API}/events**`, async (route) => {
    const query = new URL(route.request().url()).searchParams;
    queries.push(query);
    if (query.get("offset") === "20" && !failed) {
      failed = true;
      return route.fulfill({ status: 422, json: { detail: "Temporary fixture failure" } });
    }
    return route.fulfill({ json: query.get("offset") === "0" ? Array.from({ length: 20 }, (_, i) => event(i)) : [event(20)] });
  });
  await page.goto("/explore");
  await expect(page.getByRole("heading", { name: "Event 0", exact: true })).toBeVisible();
  await page.getByPlaceholder(/Search events/).fill("unsubmitted jazz");
  await page.getByRole("button", { name: "Load more", exact: true }).click();
  await expect(page.getByText(/Could not load events:/)).toBeVisible();
  await page.getByRole("button", { name: "Retry", exact: true }).click();
  await expect(page.getByRole("heading", { name: "Event 20", exact: true })).toBeVisible();
  expect(queries.filter((query) => query.get("offset") === "20")).toHaveLength(2);
  expect(queries.every((query) => !query.has("q"))).toBe(true);
  expect(queries.some((query) => query.get("offset") === "40")).toBe(false);
});

test("an older filter response cannot replace the current results", async ({ page }) => {
  let releaseOld: (() => void) | undefined;
  let oldStarted = false;
  await page.route(`${API}/events**`, async (route) => {
    const location = new URL(route.request().url()).searchParams.get("location_preset");
    if (location === "sf") {
      oldStarted = true;
      await new Promise<void>((resolve) => { releaseOld = resolve; });
      await route.fulfill({ json: [event(1, "Old SF result")] }).catch(() => {});
      return;
    }
    await route.fulfill({ json: [event(2, location === "oakland" ? "Current Oakland result" : "Initial event")] });
  });
  await page.goto("/explore");
  await expect(page.getByRole("heading", { name: "Initial event" })).toBeVisible();
  await page.getByRole("button", { name: "San Francisco", exact: true }).click();
  await expect.poll(() => oldStarted).toBe(true);
  await page.getByRole("button", { name: "Oakland", exact: true }).click();
  await expect(page.getByRole("heading", { name: "Current Oakland result" })).toBeVisible();
  releaseOld?.();
  await page.waitForTimeout(100);
  await expect(page.getByRole("heading", { name: "Old SF result" })).toHaveCount(0);
  await expect(page.getByRole("heading", { name: "Current Oakland result" })).toBeVisible();
});

test("folder filter debounces events without rebuilding recommendations or reloading the folder", async ({ page }) => {
  await signInFixture(page);
  let folderReads = 0;
  let recommendationReads = 0;
  let eventReads = 0;
  await page.route(`${API}/folders/7`, (route) => { folderReads++; return route.fulfill({ json: folder }); });
  await page.route(`${API}/recommendations**`, (route) => { recommendationReads++; return route.fulfill({ json: [] }); });
  await page.route(`${API}/events**`, (route) => {
    eventReads++;
    const tag = new URL(route.request().url()).searchParams.get("vibe_tag");
    return route.fulfill({ json: [event(3, tag ? `Suggestion ${tag}` : "Initial suggestion")] });
  });
  await page.goto("/folders/7");
  await expect(page.getByText("Initial suggestion", { exact: false })).toBeVisible();
  const before = { folderReads, recommendationReads, eventReads };
  await page.getByLabel("Vibe filter (optional)").pressSequentially("#Chill", { delay: 20 });
  await expect(page.getByText("Suggestion #Chill", { exact: false })).toBeVisible();
  expect(folderReads).toBe(before.folderReads);
  expect(recommendationReads).toBe(before.recommendationReads);
  expect(eventReads).toBe(before.eventReads + 1);
});

test("logout removes folder contents and generated invitation URLs", async ({ page }) => {
  await signInFixture(page);
  await page.route(`${API}/**`, (route) => {
    const path = new URL(route.request().url()).pathname;
    if (path === "/folders/7") return route.fulfill({ json: folder });
    if (path === "/folders/7/invite") return route.fulfill({ json: {
      folder_id: 7, invite_token: "private-invite", share_url: "/shared/folders/private-share", expires_at: null,
    } });
    return route.fulfill({ json: [] });
  });
  await page.goto("/folders/7");
  await expect(page.getByText(folder.name)).toBeVisible();
  await page.getByRole("button", { name: "Generate share link" }).click();
  await expect(page.getByRole("link", { name: /private-invite/ })).toBeVisible();
  await page.getByRole("button", { name: "Log out" }).click();
  await expect(page.getByText("Sign in to view this folder.")).toBeVisible();
  await expect(page.getByText(folder.name)).toHaveCount(0);
  await expect(page.getByRole("link", { name: /private-invite/ })).toHaveCount(0);
});

test("late recommendations cannot restore personal content after logout", async ({ page }) => {
  await signInFixture(page);
  let release: (() => void) | undefined;
  let started = false;
  await page.route(`${API}/recommendations**`, async (route) => {
    started = true;
    await new Promise<void>((resolve) => { release = resolve; });
    await route.fulfill({ json: [{ ...event(8, "Private recommendation"), match_score: 80, matched_vibes: [] }] }).catch(() => {});
  });
  await page.goto("/recommendations");
  await expect.poll(() => started).toBe(true);
  await page.getByRole("button", { name: "Log out" }).click();
  release?.();
  await expect(page.getByText("Sign in to see personalized recommendations.")).toBeVisible();
  await expect(page.getByRole("heading", { name: "Private recommendation" })).toHaveCount(0);
});

for (const mode of ["login", "signup"] as const) {
  test(`${mode} returns an invite recipient to the folder; signup preserves selected tags`, async ({ page }) => {
    let accepted = false;
    let preferences: { preferred_vibes: string[] } | undefined;
    await page.route(`${API}/**`, async (route) => {
      const path = new URL(route.request().url()).pathname;
      if (path.startsWith("/auth/")) return route.fulfill({ json: { access_token: "fixture-token", email: "me@example.test", user_id: 1 } });
      if (path === "/users/me/preferences") {
        preferences = route.request().postDataJSON();
        return route.fulfill({ json: { user_id: 1, saved_event_ids: [], ...preferences } });
      }
      if (path === "/folders/invites/fixture-invite/accept") { accepted = true; return route.fulfill({ json: folder }); }
      if (path === "/folders/7") return route.fulfill({ json: folder });
      return route.fulfill({ json: [] });
    });
    await page.goto("/invites/fixture-invite");
    await page.locator('section a[href^="/login?next="]').click();
    await expect(page).toHaveURL(/next=/);
    if (mode === "login") await page.getByRole("button", { name: "Sign in", exact: true }).click();
    await page.getByLabel("Email").fill("me@example.test");
    await page.getByLabel("Password").fill("a-long-test-password");
    await page.getByRole("button", { name: mode === "login" ? "Sign in" : "Create account", exact: true }).click();
    if (mode === "signup") {
      for (const name of [/Live Music/, /Comedy/, /Nightlife & Clubs/, /Food & Drink/]) {
        await page.getByRole("button", { name }).click();
      }
      await page.getByRole("button", { name: "Continue", exact: true }).click();
    }
    await expect(page).toHaveURL(/\/folders\/7$/);
    expect(accepted).toBe(true);
    if (mode === "signup") expect(preferences?.preferred_vibes).toEqual(["#LiveMusic", "#Comedy", "#Nightlife", "#FoodAndDrink"]);
  });
}

test("login rejects an external return destination", async ({ page }) => {
  await page.route(`${API}/auth/login`, (route) => route.fulfill({ json: { access_token: "fixture-token", email: "me@example.test", user_id: 1 } }));
  await page.route(`${API}/events**`, (route) => route.fulfill({ json: [] }));
  await page.goto("/login?next=%2F%2Fevil.example");
  await page.getByRole("button", { name: "Sign in", exact: true }).click();
  await page.getByLabel("Email").fill("me@example.test");
  await page.getByLabel("Password").fill("a-long-test-password");
  await page.getByRole("button", { name: "Sign in", exact: true }).click();
  await expect(page).toHaveURL(/\/explore$/);
});

test.describe("event times for a traveler", () => {
  test.use({ timezoneId: "Asia/Tokyo" });
  test("cards show the venue date and time", async ({ page }) => {
    await page.route(`${API}/events**`, (route) => route.fulfill({ json: [event(1)] }));
    await page.goto("/explore");
    await expect(page.getByText(/Sat, Oct 3 · 11:00 PM/)).toBeVisible();
  });
});

test("Explore reports total matches, ends pagination, and fits long titles without shifting actions", async ({ page }) => {
  const longTitle = "Entanglement: " + "Afriqua, Agonis, Carlos Souffront, Christina Chatfield, ".repeat(8);
  await page.setViewportSize({ width: 1280, height: 900 });
  await page.route(`${API}/events**`, async (route) => {
    const offset = Number(new URL(route.request().url()).searchParams.get("offset"));
    return route.fulfill({
      headers: { "X-Total-Count": "21", "Access-Control-Expose-Headers": "X-Total-Count" },
      json: offset === 0 ? Array.from({ length: 20 }, (_, i) => event(i, i === 0 ? longTitle : `Event ${i}`)) : [event(20)],
    });
  });
  await page.goto("/explore");
  await expect(page).toHaveTitle("Explore | Truth of Fun");
  await expect(page.getByText("20 of 21 events", { exact: true })).toBeVisible();
  const title = page.getByRole("heading", { name: longTitle });
  await expect(title).toHaveAttribute("title", longTitle);
  const titleBox = await title.boundingBox();
  const lineHeight = await title.evaluate((element) => Number.parseFloat(getComputedStyle(element).lineHeight));
  expect(titleBox!.height).toBeLessThanOrEqual(2 * lineHeight + 1);
  const actions = page.getByRole("button", { name: "Mark viewed", exact: true });
  const first = await actions.nth(0).boundingBox();
  const second = await actions.nth(1).boundingBox();
  expect(Math.abs(first!.y - second!.y)).toBeLessThan(1);
  await page.getByRole("button", { name: "Load more", exact: true }).click();
  await expect(page.getByText("21 of 21 events", { exact: true })).toBeVisible();
  await expect(page.getByRole("button", { name: "Load more", exact: true })).toHaveCount(0);
  await page.goto("/planner");
  await expect(page).toHaveTitle("Planner | Truth of Fun");
});
