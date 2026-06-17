import { test, expect } from "@playwright/test";

// Interaction-level coverage. Unlike the route smoke tests, these exercise
// client-side state transitions (view toggles, form gating, navigation) and
// graceful degradation. They run WITHOUT a backend — the same way CI does — so
// every assertion targets behavior that holds when the API is unreachable.

test("home 'Explore events' link navigates to the explore page", async ({ page }) => {
  await page.goto("/");
  await page.getByRole("link", { name: /Explore events/i }).click();
  await expect(page).toHaveURL(/\/explore$/);
  await expect(page.getByPlaceholder(/Search events/i)).toBeVisible();
});

test("explore: toggling between List and Map views updates the active control", async ({ page }) => {
  await page.goto("/explore");

  const listButton = page.getByRole("button", { name: "List", exact: true });
  const mapButton = page.getByRole("button", { name: "Map", exact: true });

  // List is the default view.
  await expect(listButton).toHaveAttribute("aria-pressed", "true");

  await mapButton.click();
  await expect(mapButton).toHaveAttribute("aria-pressed", "true");
  await expect(listButton).toHaveAttribute("aria-pressed", "false");
  // The map region mounts (no backend => no points, so the empty hint shows).
  await expect(page.getByRole("application", { name: /Event venue map/i })).toBeVisible();

  await listButton.click();
  await expect(listButton).toHaveAttribute("aria-pressed", "true");
});

test("explore: searching degrades gracefully with no backend", async ({ page }) => {
  await page.goto("/explore");

  const search = page.getByPlaceholder(/Search events/i);
  await search.fill("jazz");
  await page.getByRole("button", { name: "Search", exact: true }).click();

  // The typed query is preserved and the empty state renders instead of crashing.
  await expect(search).toHaveValue("jazz");
  await expect(page.getByText(/No events found/i)).toBeVisible();
});

test("planner: 'Build itinerary' is disabled until a prompt is entered", async ({ page }) => {
  await page.goto("/planner");

  const build = page.getByRole("button", { name: /Build itinerary/i });
  await expect(build).toBeDisabled();

  await page.getByPlaceholder(/plan a date in the Mission/i).fill("Bar crawl in Oakland Friday night");
  await expect(build).toBeEnabled();
});

test("planner: clicking an example prompt fills the textarea", async ({ page }) => {
  await page.goto("/planner");

  const textarea = page.getByPlaceholder(/plan a date in the Mission/i);
  await expect(textarea).toHaveValue("");

  await page.getByRole("button", { name: /Bar crawl in Oakland/i }).click();

  await expect(textarea).not.toHaveValue("");
  await expect(textarea).toHaveValue(/Bar crawl in Oakland/);
  await expect(page.getByRole("button", { name: /Build itinerary/i })).toBeEnabled();
});

test("onboarding: save is gated and 'Skip for now' navigates to explore", async ({ page }) => {
  await page.goto("/onboarding");

  await expect(page.getByRole("button", { name: /Save preferences/i })).toBeDisabled();

  await page.getByRole("button", { name: /Skip for now/i }).click();
  await expect(page).toHaveURL(/\/explore$/);
  await expect(page.getByPlaceholder(/Search events/i)).toBeVisible();
});
