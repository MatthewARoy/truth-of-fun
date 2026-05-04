import { test, expect } from "@playwright/test";

test("root welcome route renders", async ({ page }) => {
  await page.goto("/");
  await expect(page.getByRole("heading", { name: "Start in your style" })).toBeVisible();
  await expect(page.getByRole("button", { name: "Browse events now" })).toBeVisible();
});

test("onboarding route renders", async ({ page }) => {
  await page.goto("/onboarding");
  await expect(page.getByRole("heading", { name: "Onboarding" })).toBeVisible();
});

test("recommendations route renders", async ({ page }) => {
  await page.goto("/recommendations");
  await expect(page.getByRole("heading", { name: "Recommendations" })).toBeVisible();
});

test("explore route renders", async ({ page }) => {
  await page.goto("/explore");
  await expect(page.getByRole("heading", { name: "Explore Events" })).toBeVisible();
  await expect(page.getByRole("button", { name: "Apply filters" })).toBeVisible();
});

test("concierge route renders", async ({ page }) => {
  await page.goto("/concierge");
  await expect(page.getByRole("heading", { name: "Concierge Planner" })).toBeVisible();
});

test("shared folder page route resolves", async ({ page }) => {
  await page.goto("/shared/folders/example-token");
  await expect(page.getByRole("heading", { name: "Shared Folder View" })).toBeVisible();
});
