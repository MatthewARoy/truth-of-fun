import { test, expect } from "@playwright/test";
import {
  MISSING_EVENT_ID, SSR_CANCELLED_EVENT, SSR_ESTIMATED_EVENT, SSR_EVENT, UNREACHABLE_EVENT_ID_FROM,
} from "../support/fixtures.mjs";
import { API, eventFixture, mockExploreApi, signInFixture, stubRemoteImages } from "./helpers";

// These pages are rendered by the Next.js server from the fixture API that
// playwright.config.ts starts (API_INTERNAL_URL), so the metadata and JSON-LD
// asserted here are what a crawler or link-preview bot actually receives.

const meta = (page: import("@playwright/test").Page, selector: string) =>
  page.locator(selector).first().getAttribute("content");

async function jsonLd(page: import("@playwright/test").Page) {
  const scripts = page.locator('script[type="application/ld+json"]');
  await expect(scripts).toHaveCount(1);
  return JSON.parse((await scripts.textContent()) ?? "null");
}

test("event page renders the listing with tickets, calendar, directions, share and save actions", async ({ page, context, baseURL }) => {
  await stubRemoteImages(page);
  await context.grantPermissions(["clipboard-read", "clipboard-write"]);
  const interestCalls: unknown[] = [];
  await page.route(`${API}/users/me/interests`, (route) => {
    interestCalls.push(route.request().postDataJSON());
    return route.fulfill({ json: { user_id: 1, saved_event_ids: [], preferred_vibes: [] } });
  });

  const response = await page.goto(`/events/${SSR_EVENT.id}`);
  expect(response?.status()).toBe(200);

  await expect(page.getByRole("heading", { level: 1 })).toHaveText(SSR_EVENT.title);
  await expect(page.getByRole("heading", { level: 1 })).toHaveCount(1);
  await expect(page.getByTestId("event-when")).toContainText("Friday, December 4, 2026 at 8:00 PM");
  await expect(page.getByTestId("event-where")).toContainText("Fox Theater · Oakland");
  await expect(page.getByTestId("event-where")).toContainText("1807 Telegraph Ave, Oakland, CA 94612");
  await expect(page.getByTestId("event-price")).toHaveText("$45");
  await expect(page.getByText("With Thundercat")).toBeVisible();

  // The full description is plain text: paragraphs survive, markup stays inert.
  await expect(page.getByText("Doors open one hour before the show.")).toBeVisible();
  await expect(page.getByText("<script>alert('listing markup must stay inert')</script>")).toBeVisible();
  for (const label of ["Music", "#LiveMusic", "#HighEnergy"]) {
    await expect(page.getByRole("listitem").filter({ hasText: new RegExp(`^${label}$`) })).toBeVisible();
  }
  await expect(page.getByText("This listing comes from ticketmaster.")).toBeVisible();

  const image = page.locator(`img[src="${SSR_EVENT.image_url}"]`);
  await expect(image).toHaveAttribute("referrerpolicy", "no-referrer");

  const tickets = page.getByRole("link", { name: "Tickets and info" });
  await expect(tickets).toHaveAttribute("href", SSR_EVENT.external_url!);
  await expect(tickets).toHaveAttribute("target", "_blank");
  await expect(tickets).toHaveAttribute("rel", "noopener noreferrer");
  await expect(page.getByRole("link", { name: "Add to calendar" }))
    .toHaveAttribute("href", `${API}/events/${SSR_EVENT.id}/calendar.ics`);
  await expect(page.getByRole("link", { name: "Directions" }))
    .toHaveAttribute("href", "https://www.google.com/maps/dir/?api=1&destination=37.8087%2C-122.2703");

  await page.getByRole("button", { name: "Copy link" }).click();
  await expect(page.getByRole("button", { name: "Link copied" })).toBeVisible();
  expect(await page.evaluate(() => navigator.clipboard.readText())).toBe(`${baseURL}/events/${SSR_EVENT.id}`);

  // Anonymous visitors are asked to sign in, and nothing about them is recorded.
  await page.getByRole("button", { name: "Save", exact: true }).click();
  await expect(page.getByRole("link", { name: "Sign in" }).last())
    .toHaveAttribute("href", `/login?next=${encodeURIComponent(`/events/${SSR_EVENT.id}`)}`);
  expect(interestCalls).toEqual([]);
});

test("event page metadata: title, description, canonical, Open Graph, Twitter card and schema.org Event", async ({ page }) => {
  await stubRemoteImages(page);
  await page.goto(`/events/${SSR_EVENT.id}`);
  await expect(page).toHaveTitle(`${SSR_EVENT.title} | Truth of Fun`);

  const description = await meta(page, 'meta[name="description"]');
  expect(description).toContain("Friday, December 4, 2026 at 8:00 PM · Fox Theater · Oakland.");
  expect(description).toContain("An evening of bass and strings at the Fox.");
  expect(description!.length).toBeLessThanOrEqual(260);

  await expect(page.locator('link[rel="canonical"]')).toHaveAttribute("href", /\/events\/101$/);
  expect(await meta(page, 'meta[property="og:title"]')).toBe(`${SSR_EVENT.title} | Truth of Fun`);
  expect(await meta(page, 'meta[property="og:description"]')).toBe(description);
  expect(await meta(page, 'meta[property="og:url"]')).toMatch(/\/events\/101$/);
  expect(await meta(page, 'meta[property="og:image"]')).toBe(SSR_EVENT.image_url);
  expect(await meta(page, 'meta[property="og:site_name"]')).toBe("Truth of Fun");
  expect(await meta(page, 'meta[name="twitter:card"]')).toBe("summary_large_image");
  expect(await meta(page, 'meta[name="twitter:image"]')).toBe(SSR_EVENT.image_url);
  await expect(page.locator('meta[name="robots"][content*="noindex"]')).toHaveCount(0);

  const data = await jsonLd(page);
  expect(data).toMatchObject({
    "@context": "https://schema.org",
    "@type": "Event",
    name: SSR_EVENT.title,
    startDate: SSR_EVENT.start_at,
    eventStatus: "https://schema.org/EventScheduled",
    image: [SSR_EVENT.image_url],
    location: {
      "@type": "Place", name: "Fox Theater", address: "1807 Telegraph Ave, Oakland, CA 94612",
      geo: { "@type": "GeoCoordinates", latitude: 37.8087, longitude: -122.2703 },
    },
    offers: { "@type": "Offer", price: 45, priceCurrency: "USD", url: SSR_EVENT.external_url },
    performer: [{ "@type": "PerformingGroup", name: "Thundercat" }],
    organizer: { "@type": "Organization", name: "Another Planet Entertainment" },
  });
  expect(data.url).toMatch(/\/events\/101$/);
  // Listing text cannot break out of the JSON-LD script element.
  expect(await page.locator('script[type="application/ld+json"]').innerHTML()).not.toContain("<script");
});

test("link-preview bots get the share tags and JSON-LD in the initial HTML", async ({ request }) => {
  const response = await request.get(`/events/${SSR_EVENT.id}`, {
    headers: { "User-Agent": "facebookexternalhit/1.1 (+http://www.facebook.com/externalhit_uatext.php)" },
  });
  expect(response.status()).toBe(200);
  const html = await response.text();
  const head = html.slice(0, html.indexOf("</head>"));
  expect(head).toContain(`<title>${SSR_EVENT.title} | Truth of Fun</title>`);
  expect(head).toMatch(/<meta property="og:title" content="Thundercat with the Oakland Symphony \| Truth of Fun"/);
  expect(head).toMatch(/<meta property="og:image" content="https:\/\/images\.example\/thundercat\.jpg"/);
  expect(head).toMatch(/<link rel="canonical" href="[^"]+\/events\/101"/);
  expect(html).toContain('<script type="application/ld+json">');
  expect(html).toContain('"@type":"Event"');
  // Server-rendered content, not a client-only shell.
  expect(html).toContain("Fox Theater · Oakland");
});

test("an estimated start never shows a clock time, and unsafe links and images are dropped", async ({ page }) => {
  await page.goto(`/events/${SSR_ESTIMATED_EVENT.id}`);
  await expect(page.getByRole("heading", { level: 1 })).toHaveText(SSR_ESTIMATED_EVENT.title);
  const when = page.getByTestId("event-when");
  await expect(when).toContainText("Sunday, December 6, 2026 · time to be announced");
  await expect(when).toContainText("The source lists a date but no start time.");
  await expect(page.locator("main")).not.toContainText(/\d{1,2}:\d{2}\s?(AM|PM)/);
  await expect(page.getByTestId("event-price")).toHaveText("Free");
  await expect(page.getByTestId("event-where")).toHaveText("Valencia Street · San Francisco");

  // javascript: ticket URL and http image from the listing are not rendered.
  await expect(page.locator('a[href^="javascript:"]')).toHaveCount(0);
  await expect(page.getByRole("link", { name: /Tickets|Event page/ })).toHaveCount(0);
  await expect(page.locator("main img")).toHaveCount(0);
  // Low-confidence coordinates are not offered as a destination; the venue name is.
  await expect(page.getByRole("link", { name: "Directions" })).toHaveAttribute(
    "href", `https://www.google.com/maps/dir/?api=1&destination=${encodeURIComponent("Valencia Street, San Francisco")}`
  );

  const description = await meta(page, 'meta[name="description"]');
  expect(description).toContain("Sunday, December 6, 2026 · time to be announced");
  expect(description).not.toMatch(/\d{1,2}:\d{2}/);
  expect(await meta(page, 'meta[name="twitter:card"]')).toBe("summary");
  await expect(page.locator('meta[property="og:image"]')).toHaveCount(0);

  const data = await jsonLd(page);
  expect(data.startDate).toBe("2026-12-06");
  expect(data.offers).toEqual({ "@type": "Offer", price: 0, priceCurrency: "USD" });
  expect(data.location).toEqual({
    "@type": "Place", name: "Valencia Street",
    address: { "@type": "PostalAddress", addressLocality: "San Francisco", addressRegion: "CA", addressCountry: "US" },
  });
  expect(data).not.toHaveProperty("image");
  expect(data).not.toHaveProperty("endDate");
});

test("a cancelled event says so, calls the date the original, and offers no calendar download", async ({ page }) => {
  await page.goto(`/events/${SSR_CANCELLED_EVENT.id}`);
  await expect(page.getByRole("heading", { level: 1 })).toHaveText(SSR_CANCELLED_EVENT.title);
  await expect(page.getByText("Cancelled.", { exact: true })).toBeVisible();
  await expect(page.locator("dt").first()).toHaveText("Originally");
  await expect(page.getByRole("link", { name: "Add to calendar" })).toHaveCount(0);
  expect(await meta(page, 'meta[name="description"]')).toMatch(/^Cancelled\. Originally Friday, December 4, 2026/);
  expect((await jsonLd(page)).eventStatus).toBe("https://schema.org/EventCancelled");
});

test("an unknown or malformed event id is a real 404 with the not-found page", async ({ page }) => {
  for (const path of [`/events/${MISSING_EVENT_ID}`, "/events/not-a-number", "/events/0", "/events/1e3"]) {
    const response = await page.goto(path);
    expect(response?.status(), path).toBe(404);
    await expect(page.getByRole("heading", { level: 1, name: "We couldn't find that page" })).toBeVisible();
    await expect(page.getByRole("main").getByRole("link", { name: "Explore events" })).toHaveAttribute("href", "/explore");
    await expect(page.getByRole("link", { name: "Go to the home page" })).toHaveAttribute("href", "/");
    await expect(page.locator('meta[name="robots"][content*="noindex"]')).not.toHaveCount(0);
  }
});

test("when the server cannot reach the API the browser loads the event itself", async ({ page }) => {
  const id = UNREACHABLE_EVENT_ID_FROM + 1;
  let calls = 0;
  await page.route(`${API}/events/${id}`, (route) => {
    calls++;
    if (calls === 1) return route.fulfill({ status: 503, json: { detail: "Service unavailable" } });
    return route.fulfill({ json: { ...SSR_EVENT, id, title: "Loaded in the browser", image_url: null } });
  });
  // retries: the API client retries a transient GET once on its own.
  const response = await page.goto(`/events/${id}`);
  expect(response?.status()).toBe(200);
  await expect(page).toHaveTitle("Event | Truth of Fun");
  await expect(page.getByRole("heading", { level: 1, name: "Loaded in the browser" })).toBeVisible();
  await expect(page.getByRole("link", { name: "Add to calendar" })).toHaveAttribute("href", `${API}/events/${id}/calendar.ics`);

  // ...and a browser-side 404 or failure is explained rather than left blank.
  const missing = id + 1;
  await page.route(`${API}/events/${missing}`, (route) => route.fulfill({ status: 404, json: { detail: "Event not found." } }));
  await page.goto(`/events/${missing}`);
  await expect(page.getByRole("heading", { level: 1, name: "We couldn't find that event" })).toBeVisible();

  const broken = id + 2;
  let healthy = false;
  await page.route(`${API}/events/${broken}`, (route) => healthy
    ? route.fulfill({ json: { ...SSR_EVENT, id: broken, title: "Recovered event", image_url: null } })
    : route.fulfill({ status: 400, json: { detail: "Fixture failure" } }));
  await page.goto(`/events/${broken}`);
  await expect(page.getByRole("main").getByRole("alert")).toContainText("Could not load this event: Fixture failure");
  healthy = true;
  await page.getByRole("button", { name: "Retry" }).click();
  await expect(page.getByRole("heading", { level: 1, name: "Recovered event" })).toBeVisible();
});

test("signed-in: opening an event records one view, and Save and ticket clicks are recorded", async ({ page }) => {
  await signInFixture(page);
  await stubRemoteImages(page);
  await page.route("https://tickets.example/**", (route) => route.fulfill({ contentType: "text/html", body: "<title>tickets</title>" }));
  const calls: Array<{ action: string; event_id: number; auth: string | undefined }> = [];
  await page.route(`${API}/users/me/interests`, (route) => {
    calls.push({ ...route.request().postDataJSON(), auth: route.request().headers().authorization });
    return route.fulfill({ json: { user_id: 1, saved_event_ids: [SSR_EVENT.id], preferred_vibes: [] } });
  });
  await page.goto(`/events/${SSR_EVENT.id}`);
  await expect.poll(() => calls).toEqual([{ action: "click", event_id: SSR_EVENT.id, auth: "Bearer fixture-token" }]);

  await page.getByRole("button", { name: "Save", exact: true }).click();
  await expect(page.getByRole("button", { name: "Saved", exact: true })).toBeDisabled();
  await expect(page.getByRole("status").filter({ hasText: "Saved to your profile." })).toBeVisible();

  const [popup] = await Promise.all([
    page.waitForEvent("popup"),
    page.getByRole("link", { name: "Tickets and info" }).click(),
  ]);
  await popup.close();
  await expect.poll(() => calls.map((call) => call.action)).toEqual(["click", "save", "external_ticket_click"]);
});

test("an event card's title opens the event page", async ({ page }) => {
  await stubRemoteImages(page);
  await mockExploreApi(page, {
    events: () => [eventFixture(SSR_EVENT.id, { title: SSR_EVENT.title, city: "Oakland" })],
  });
  await page.goto("/explore");
  await page.getByRole("link", { name: SSR_EVENT.title, exact: true }).click();
  await expect(page).toHaveURL(new RegExp(`/events/${SSR_EVENT.id}$`));
  await expect(page.getByRole("heading", { level: 1 })).toHaveText(SSR_EVENT.title);
  await expect(page.getByRole("link", { name: /All events/ })).toHaveAttribute("href", "/explore");
});
