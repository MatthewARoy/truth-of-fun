import { test, expect } from "@playwright/test";

test("home route renders hero", async ({ page }) => {
  await page.goto("/");
  await expect(
    page.getByRole("heading", { name: /fragmented event landscape/i })
  ).toBeVisible();
  await expect(page.getByRole("link", { name: /Explore events/i })).toBeVisible();
});

test("explore route renders filter chips", async ({ page }) => {
  await page.goto("/explore");
  await expect(
    page.getByPlaceholder(/Search events/i)
  ).toBeVisible();
  await expect(page.getByRole("button", { name: "Search", exact: true })).toBeVisible();
  await expect(page.getByRole("button", { name: "Map", exact: true })).toBeVisible();
});

test("planner route renders form", async ({ page }) => {
  await page.goto("/planner");
  await expect(page.getByRole("heading", { name: /Plan Something/i })).toBeVisible();
  await expect(page.getByRole("button", { name: /Build itinerary/i })).toBeVisible();
});

test("concierge route renders", async ({ page }) => {
  await page.goto("/concierge");
  await expect(page.getByRole("heading", { name: "Concierge Planner" })).toBeVisible();
});

test("onboarding route renders", async ({ page }) => {
  await page.goto("/onboarding");
  await expect(page.getByRole("heading", { name: "Onboarding" })).toBeVisible();
});

test("recommendations route renders", async ({ page }) => {
  await page.goto("/recommendations");
  await expect(page.getByRole("heading", { name: "Recommendations" })).toBeVisible();
});

test("admin source health route renders", async ({ page }) => {
  await page.goto("/admin/sources");
  await expect(page.getByRole("heading", { name: /Source Health/i })).toBeVisible();
});

test("shared folder page route resolves", async ({ page }) => {
  await page.goto("/shared/folders/example-token");
  await expect(page.getByRole("heading", { name: "Shared Folder View" })).toBeVisible();
});
