import { test, expect } from "@playwright/test";

// A postponed or cancelled show must never read as happening. The event card
// never looked at `status`, so Dan and Phil's postponed Palace of Fine Arts
// date rendered exactly like a show you could go to. Stubs the API at the
// network layer, like shared-itinerary.spec.ts, so no backend is needed.

const API_BASE = process.env.NEXT_PUBLIC_API_BASE_URL || "http://127.0.0.1:8000";

function eventResponse(id: number, title: string, status: string) {
  return {
    id,
    title,
    description: null,
    start_at: "2026-09-14T02:30:00Z",
    start_time_is_estimated: false,
    end_at: null,
    external_url: null,
    venue_name: "Palace of Fine Arts",
    tags: [],
    categories: [],
    image_url: null,
    price: null,
    currency: null,
    status,
    people_interested: 0,
    distance_miles: null,
    lat: 37.8019,
    lng: -122.4482,
    organizer_name: null,
    attendee_count: 0,
    location_confidence: 1,
    is_free: false,
  };
}

const EVENTS = [
  eventResponse(1, "Dan and Phil: Hard Launch World Tour", "postponed"),
  eventResponse(2, "Insecure: The 10th Anniversary Tour", "cancelled"),
  eventResponse(3, "KATHY GRIFFIN: New Face, New Tour", "scheduled"),
];

test("explore never presents a postponed or cancelled event as happening", async ({ page }) => {
  await page.route(`${API_BASE}/events*`, (route) => route.fulfill({ json: EVENTS }));

  await page.goto("/explore");

  const card = (title: string) => page.getByRole("article").filter({ hasText: title });

  const postponed = card("Dan and Phil");
  await expect(postponed).toContainText("Postponed");
  await expect(postponed).toContainText("Originally");

  const cancelled = card("Insecure");
  await expect(cancelled).toContainText("Cancelled");
  await expect(cancelled).toContainText("Originally");

  const scheduled = card("KATHY GRIFFIN");
  await expect(scheduled).toBeVisible();
  await expect(scheduled).not.toContainText(/Postponed|Cancelled|Originally/);
});
