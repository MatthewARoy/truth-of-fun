import { test, expect } from "@playwright/test";
import { SSR_FOLDER, SSR_FOLDER_TOKEN, SSR_PLAN, SSR_PLAN_TOKEN } from "../support/fixtures.mjs";
import { API, eventFixture, mockExploreApi, signInFixture, storedSession } from "./helpers";

test("a render crash shows the styled error page with retry and a way home, never a stack trace", async ({ page }) => {
  let healthy = false;
  // `tags` is not an array: the event card throws while rendering.
  await mockExploreApi(page, {
    events: () => [eventFixture(1, healthy ? { title: "Recovered event" } : { tags: "not-a-list" })],
  });
  await page.goto("/explore");

  const main = page.getByRole("main");
  await expect(main.getByRole("heading", { level: 1, name: "Something went wrong" })).toBeVisible();
  await expect(main.getByRole("link", { name: "Go to the home page" })).toHaveAttribute("href", "/");
  // The site chrome survives, and nothing technical is shown to the visitor.
  await expect(page.getByRole("navigation", { name: "Main" })).toBeVisible();
  const text = await main.innerText();
  expect(text).not.toMatch(/TypeError|is not a function|\bat \w+ \(|webpack|node_modules|\.tsx?:\d+/);

  healthy = true;
  await main.getByRole("button", { name: "Try again" }).click();
  await expect(page.getByRole("heading", { name: "Recovered event" })).toBeVisible();
  await expect(main.getByRole("heading", { name: "Something went wrong" })).toHaveCount(0);
});

test("an unknown URL is a 404 with the styled not-found page", async ({ page }) => {
  const response = await page.goto("/definitely/not/a/page");
  expect(response?.status()).toBe(404);
  await expect(page).toHaveTitle("Page not found | Truth of Fun");
  await expect(page.getByRole("heading", { level: 1, name: "We couldn't find that page" })).toBeVisible();
  await expect(page.getByRole("navigation", { name: "Main" })).toBeVisible();
  await page.getByRole("link", { name: "Go to the home page" }).click();
  await expect(page).toHaveURL(/\/$/);
  await expect(page.getByRole("heading", { level: 1, name: /something fun to do/i })).toBeVisible();
});

test("an expired session is cleared and the user is sent to sign in, then returned", async ({ page }) => {
  await signInFixture(page);
  let valid = false;
  const folder = { id: 3, name: "Weekend ideas", share_token: "s", created_at: "2026-01-01T00:00:00Z" };
  await page.route(`${API}/folders`, (route) => {
    const auth = route.request().headers().authorization;
    if (valid && auth === "Bearer fresh-token") return route.fulfill({ json: [folder] });
    return route.fulfill({ status: 401, json: { detail: "Token has expired." } });
  });
  await page.route(`${API}/auth/login`, (route) => {
    valid = true;
    return route.fulfill({ json: { access_token: "fresh-token", token_type: "bearer", email: "me@example.test", user_id: 1 } });
  });

  await page.goto("/folders?from=bookmark");
  await expect(page).toHaveURL(/\/login\?reason=expired&next=%2Ffolders%3Ffrom%3Dbookmark$/);
  expect(await storedSession(page)).toBeNull();
  await expect(page.getByText("Your session has ended. Sign in again to pick up where you left off.")).toBeVisible();
  await expect(page.getByRole("navigation", { name: "Main" }).getByRole("link", { name: "Sign in" })).toBeVisible();
  await expect(page.getByRole("button", { name: "Log out" })).toHaveCount(0);

  // The form is already in sign-in mode; signing in returns to the page they wanted.
  await expect(page.getByRole("heading", { level: 1, name: "Welcome back" })).toBeVisible();
  await page.getByLabel("Email").fill("me@example.test");
  await page.getByLabel("Password").fill("a-long-test-password");
  await page.getByRole("button", { name: "Sign in", exact: true }).click();
  await expect(page).toHaveURL(/\/folders\?from=bookmark$/);
  await expect(page.getByText("Weekend ideas")).toBeVisible();
  expect((await storedSession(page)).token).toBe("fresh-token");
});

test("a revoked token on a background request also ends the session", async ({ page }) => {
  await signInFixture(page);
  await page.route(`${API}/recommendations**`, (route) =>
    route.fulfill({ status: 401, json: { detail: "Token has been revoked." } }));
  await page.goto("/recommendations");
  await expect(page).toHaveURL(/\/login\?reason=expired&next=%2Frecommendations$/);
  expect(await storedSession(page)).toBeNull();
});

test("a wrong password is an error on the form, not an expired session", async ({ page }) => {
  await signInFixture(page);
  await page.route(`${API}/auth/login`, (route) =>
    route.fulfill({ status: 401, json: { detail: "Invalid email or password." } }));
  await page.goto("/login");
  await page.getByRole("button", { name: "Sign in", exact: true }).click();
  await page.getByLabel("Email").fill("me@example.test");
  await page.getByLabel("Password").fill("wrong-password-123");
  await page.getByRole("button", { name: "Sign in", exact: true }).click();
  await expect(page.getByRole("main").getByRole("alert")).toHaveText("Invalid email or password.");
  await expect(page).toHaveURL(/\/login$/);
  await expect(page.getByText("Your session has ended")).toHaveCount(0);
  // The existing session in this browser was not thrown away by the failed attempt.
  expect((await storedSession(page)).token).toBe("fixture-token");
});

test("validation errors from the API are readable", async ({ page }) => {
  await page.route(`${API}/auth/register`, (route) => route.fulfill({
    status: 422,
    json: { detail: [{ loc: ["body", "email"], msg: "value is not a valid email address", type: "value_error" }] },
  }));
  await page.goto("/login");
  await page.getByLabel("Email").fill("me@example.test");
  await page.getByLabel("Password").fill("a-long-test-password");
  await page.getByRole("button", { name: "Create account", exact: true }).click();
  await expect(page.getByRole("main").getByRole("alert")).toHaveText("email: value is not a valid email address");
});

test("read requests are CORS-simple: no Content-Type on GET", async ({ page }) => {
  const headers: Array<Record<string, string>> = [];
  await page.route(`${API}/regions`, (route) => route.fulfill({ json: { regions: [] } }));
  await page.route((url) => url.href.startsWith(`${API}/events?`), (route) => {
    headers.push(route.request().headers());
    return route.fulfill({ json: [] });
  });
  await page.goto("/explore");
  await expect(page.getByText("No events found.")).toBeVisible();
  expect(headers.length).toBeGreaterThan(0);
  for (const sent of headers) expect(sent).not.toHaveProperty("content-type");
});

test("healthz answers 200 ok as uncached plain text", async ({ request }) => {
  const response = await request.get("/healthz");
  expect(response.status()).toBe(200);
  expect(await response.text()).toBe("ok");
  expect(response.headers()["content-type"]).toMatch(/^text\/plain/);
  expect(response.headers()["cache-control"]).toContain("no-store");
});

test("security headers: CSP, HSTS, geolocation for this origin only, no framework banner", async ({ request }) => {
  for (const path of ["/", "/explore", "/events/101", "/healthz"]) {
    const headers = (await request.get(path)).headers();
    const csp = headers["content-security-policy"];
    expect(csp, path).toContain("default-src 'self'");
    expect(csp).toContain("frame-ancestors 'none'");
    expect(csp).toContain("object-src 'none'");
    expect(csp).toContain("base-uri 'self'");
    expect(csp).toContain("img-src 'self' data: blob: https:");
    // Only this site and the configured API origin may be contacted.
    expect(csp).toMatch(new RegExp(`connect-src 'self' ${API.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")}( ws:)?;`));
    expect(headers["strict-transport-security"]).toMatch(/max-age=\d{8,}/);
    expect(headers["permissions-policy"]).toBe("camera=(), microphone=(), geolocation=(self)");
    expect(headers["x-content-type-options"]).toBe("nosniff");
    expect(headers["x-frame-options"]).toBe("DENY");
    expect(headers).not.toHaveProperty("x-powered-by");
  }
});

test("robots.txt and sitemap.xml list the public site and upcoming events", async ({ request }) => {
  const robots = await (await request.get("/robots.txt")).text();
  expect(robots).toMatch(/User-Agent: \*/i);
  expect(robots).toMatch(/Sitemap: https?:\/\/\S+\/sitemap\.xml/);
  for (const path of ["/admin/", "/account", "/folders", "/invites/", "/shared-plans"]) {
    expect(robots).toContain(`Disallow: ${path}`);
  }
  // Share pages must stay fetchable by link-preview bots (they are noindex instead).
  expect(robots).not.toMatch(/Disallow: \/(itinerary|shared\/)/);
  expect(robots).not.toMatch(/Disallow: \/(explore|events)/);

  const response = await request.get("/sitemap.xml");
  expect(response.status()).toBe(200);
  expect(response.headers()["content-type"]).toContain("xml");
  const xml = await response.text();
  const locs = [...xml.matchAll(/<loc>([^<]+)<\/loc>/g)].map((match) => new URL(match[1]).pathname);
  expect(locs).toEqual(expect.arrayContaining(["/", "/explore", "/planner", "/privacy", "/terms", "/events/101", "/events/102"]));
  // Cancelled events and private areas are not advertised.
  expect(locs).not.toContain("/events/103");
  expect(locs.some((path) => /^\/(account|login|folders|admin|itinerary|shared)/.test(path))).toBe(false);
});

test("share pages get their own preview metadata and are never indexed", async ({ page }) => {
  await page.route(`${API}/shared/itineraries/*`, (route) => route.fulfill({ json: SSR_PLAN }));
  await page.route(`${API}/shared/folders/*`, (route) => route.fulfill({ json: SSR_FOLDER }));
  const content = (selector: string) => page.locator(selector).first().getAttribute("content");

  await page.goto(`/itinerary/${SSR_PLAN_TOKEN}`);
  await expect(page).toHaveTitle(`${SSR_PLAN.title} | Truth of Fun`);
  expect(await content('meta[property="og:title"]')).toBe(`${SSR_PLAN.title} | Truth of Fun`);
  expect(await content('meta[property="og:description"]'))
    .toBe("2 stops: Happy hour at True Laurel → Julien Baker at The Chapel");
  expect(await content('meta[name="twitter:card"]')).toBe("summary");
  expect(await content('meta[name="robots"]')).toContain("noindex");

  await page.goto(`/shared/folders/${SSR_FOLDER_TOKEN}`);
  await expect(page).toHaveTitle(`${SSR_FOLDER.name} | Truth of Fun`);
  expect(await content('meta[property="og:description"]')).toContain("2 events on the shortlist: Thundercat");
  expect(await content('meta[name="robots"]')).toContain("noindex");

  // Unknown tokens (or an unreachable API) fall back to generic text.
  await page.goto("/itinerary/unknown-token");
  await expect(page).toHaveTitle("Shared itinerary | Truth of Fun");
  expect(await content('meta[property="og:title"]')).toBe("Shared itinerary | Truth of Fun");
  expect(await content('meta[name="robots"]')).toContain("noindex");
  await page.goto("/shared/folders/unknown-token");
  await expect(page).toHaveTitle("Shared folder | Truth of Fun");
  expect(await content('meta[name="robots"]')).toContain("noindex");
});

test("private pages are noindex; public pages are indexable with a canonical URL", async ({ page }) => {
  await page.route(`${API}/**`, (route) => route.fulfill({ json: [] }));
  const noindex = page.locator('meta[name="robots"][content*="noindex"]');
  for (const path of [
    "/login", "/forgot-password", "/reset-password", "/account", "/folders", "/folders/7", "/shared-plans",
    "/invites/some-token", "/admin/sources", "/recommendations", "/onboarding",
  ]) {
    await page.goto(path);
    await expect(noindex, path).toHaveCount(1);
  }
  for (const path of ["/", "/explore", "/planner", "/privacy", "/terms"]) {
    await page.goto(path);
    await expect(noindex, path).toHaveCount(0);
    await expect(page.locator('link[rel="canonical"]'), path).toHaveAttribute("href", new RegExp(`${path === "/" ? "" : path}/?$`));
  }
  await page.goto("/");
  await expect(page).toHaveTitle("Truth of Fun — Things to do around the San Francisco Bay Area");
  await expect(page.locator('link[rel="icon"]').first()).toHaveAttribute("href", /icon\.svg/);
});

test("every page has one h1, with the header and nav outside main", async ({ page }) => {
  await page.route(`${API}/**`, (route) => route.fulfill({ json: [] }));
  for (const path of ["/", "/explore", "/planner", "/login", "/forgot-password", "/reset-password?token=t", "/privacy", "/terms", "/account", "/recommendations", "/onboarding", "/events/101"]) {
    await page.goto(path);
    await expect(page.locator("h1"), path).toHaveCount(1);
    await expect(page.locator("main"), path).toHaveCount(1);
    await expect(page.locator("main h1"), path).toHaveCount(1);
    await expect(page.locator("main header nav, main > header")).toHaveCount(0);
    await expect(page.locator("body header").first().getByRole("navigation", { name: "Main" })).toBeVisible();
    await expect(page.getByRole("contentinfo").getByRole("link", { name: "Privacy" })).toHaveAttribute("href", "/privacy");
    await expect(page.getByRole("contentinfo").getByRole("link", { name: "Terms" })).toHaveAttribute("href", "/terms");
  }
});

test("home and legal pages: resident-facing copy, draft notices, no engineering jargon", async ({ page }) => {
  await page.goto("/");
  const home = await page.getByRole("main").innerText();
  expect(home).not.toMatch(/Levenshtein|reference deployment|scraped|dedupe|canary|connector/i);
  for (const region of ["San Francisco", "East Bay", "Peninsula", "South Bay", "North Bay"]) {
    await expect(page.getByRole("main").getByRole("link", { name: new RegExp(`^${region}`) })).toBeVisible();
  }
  await expect(page.getByRole("main").getByRole("link", { name: "Explore events" })).toHaveAttribute("href", "/explore");
  await expect(page.getByRole("main").getByRole("link", { name: "Plan something" })).toHaveAttribute("href", "/planner");

  for (const [path, heading] of [["/privacy", "Privacy Policy (draft)"], ["/terms", "Terms of Use (draft)"]] as const) {
    await page.goto(path);
    await expect(page.getByRole("heading", { level: 1, name: heading })).toBeVisible();
    const notice = page.getByRole("note", { name: "Draft notice" });
    await expect(notice).toContainText("Draft: pending legal review");
    await expect(notice).toContainText("must not be relied on");
    // The notice comes before the document itself.
    expect((await notice.boundingBox())!.y).toBeLessThan((await page.getByRole("heading", { level: 1 }).boundingBox())!.y);
    await expect(page.getByRole("main")).toContainText("[Company legal name]");
    await expect(page.getByRole("main")).toContainText("[contact email]");
  }
});
