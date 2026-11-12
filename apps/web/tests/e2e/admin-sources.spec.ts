import { test, expect } from "@playwright/test";
import { API } from "./helpers";

const source = (name: string, status: string, extra: Record<string, unknown> = {}) => ({
  name, status, last_run_at: new Date().toISOString(), last_event_count: 40, consecutive_zeros: 0,
  last_error: null, last_error_at: null, last_success_at: new Date().toISOString(), is_stale: false,
  ...extra,
});

test("source health: disabled sources are muted and uncounted; degraded rows explain themselves", async ({ page }) => {
  await page.route(`${API}/health/sources`, (route) => route.fulfill({ json: { sources: [
    source("ticketmaster", "healthy"),
    source("stanford_events", "healthy"),
    source("sjsu_events", "healthy"),
    source("oakland_library", "degraded", { last_error: "Stopped at the page budget (20 pages); more events remain." }),
    source("san_jose_library", "healthy"),
    source("eventbrite", "disabled", {
      last_run_at: null, last_event_count: null, last_success_at: null, is_stale: true,
      last_error: "EVENTBRITE_API_TOKEN is not set.",
    }),
  ] } }));
  await page.route(`${API}/health/summary`, (route) => route.fulfill({ json: {
    status: "ok", checked_at: new Date().toISOString(), problems: [], database: { connected: true },
    sources: { total: 6, by_status: { healthy: 4, degraded: 1, disabled: 1 }, stale: 0, worker_stalled: false },
    events: {},
  } }));
  await page.goto("/admin/sources");
  const row = (name: string) => page.getByRole("row").filter({ hasText: name });

  // The four new sources are tier 2.
  for (const name of ["stanford_events", "sjsu_events", "oakland_library", "san_jose_library"]) {
    await expect(row(name).getByRole("cell").nth(1)).toHaveText("T2");
  }

  // Disabled: a quiet badge, never "stale", with its reason shown but not in alarm red.
  const disabled = row("eventbrite");
  await expect(disabled.getByRole("cell").nth(2)).toContainText("disabled");
  await expect(disabled.getByRole("cell").nth(2)).not.toContainText("stale");
  const reason = disabled.getByText("EVENTBRITE_API_TOKEN is not set.");
  await expect(reason).toBeVisible();
  await expect(reason).not.toHaveClass(/rose|amber/);
  await expect(disabled.locator("span.rounded-full").first()).not.toHaveClass(/emerald|rose|amber/);

  // It is not counted as healthy, degraded or failing, and does not spoil the verdict.
  const count = (label: string) => page.getByText(label, { exact: true }).locator("xpath=following-sibling::div");
  await expect(count("Healthy")).toHaveText("4");
  await expect(count("Degraded")).toHaveText("1");
  await expect(count("Failing")).toHaveText("0");
  await expect(page.getByTestId("disabled-sources-note")).toContainText("1 optional source is disabled");
  await expect(page.getByText("All enabled sources healthy and the corpus is fresh.")).toBeVisible();

  // Degraded shows why (here: the page budget), as a warning rather than an error.
  const degraded = row("oakland_library").getByText("Stopped at the page budget (20 pages); more events remain.");
  await expect(degraded).toBeVisible();
  await expect(degraded).toHaveClass(/amber/);
});
