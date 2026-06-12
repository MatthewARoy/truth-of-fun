/**
 * Capture UI screenshots for README using Playwright.
 *
 * Assumes:
 *   - Web is running on http://127.0.0.1:3000 (make web)
 *   - API is running on http://127.0.0.1:8000 (make api)
 *   - Database is seeded (make seed)
 *
 * Output: docs/screenshots/{name}.jpg
 */
import { chromium } from "playwright";
import { mkdir } from "node:fs/promises";
import { resolve, dirname } from "node:path";
import { fileURLToPath } from "node:url";

const __dirname = dirname(fileURLToPath(import.meta.url));
const OUT_DIR = resolve(__dirname, "../docs/screenshots");
const WEB_BASE = process.env.WEB_BASE || "http://127.0.0.1:3000";
const API_BASE = process.env.API_BASE || "http://127.0.0.1:8000";

const SHOTS = [
  { name: "01-home", path: "/", waitFor: 'h2:has-text("fragmented")' },
  { name: "02-explore", path: "/explore", waitFor: 'h3', extraDelayMs: 1500 },
  { name: "03-explore-map", path: "/explore", waitFor: 'h3', extraDelayMs: 1500, interact: "map" },
  { name: "04-planner", path: "/planner", waitFor: 'button:has-text("Build itinerary")', interact: "planner" },
  { name: "05-recommendations", path: "/recommendations", waitFor: 'h2', auth: true, extraDelayMs: 1500 },
  { name: "06-onboarding-vibes", path: "/login", waitFor: 'h2', interact: "vibes" },
  { name: "07-admin-sources", path: "/admin/sources", waitFor: 'h2:has-text("Source Health")', interact: "stubHealth", extraDelayMs: 600 },
];

const DEMO_HEALTH = {
  sources: [
    { name: "ticketmaster", status: "healthy", last_run_at: new Date(Date.now() - 12 * 60 * 1000).toISOString(), last_event_count: 487, consecutive_zeros: 0 },
    { name: "eventbrite", status: "healthy", last_run_at: new Date(Date.now() - 12 * 60 * 1000).toISOString(), last_event_count: 312, consecutive_zeros: 0 },
    { name: "meetup", status: "healthy", last_run_at: new Date(Date.now() - 12 * 60 * 1000).toISOString(), last_event_count: 156, consecutive_zeros: 0 },
    { name: "funcheap_sf", status: "healthy", last_run_at: new Date(Date.now() - 12 * 60 * 1000).toISOString(), last_event_count: 78, consecutive_zeros: 0 },
    { name: "19hz", status: "degraded", last_run_at: new Date(Date.now() - 12 * 60 * 1000).toISOString(), last_event_count: 0, consecutive_zeros: 1 },
    { name: "luma", status: "failing", last_run_at: new Date(Date.now() - 12 * 60 * 1000).toISOString(), last_event_count: 0, consecutive_zeros: 3 },
    { name: "dothebay", status: "healthy", last_run_at: new Date(Date.now() - 12 * 60 * 1000).toISOString(), last_event_count: 92, consecutive_zeros: 0 },
    { name: "sfstation", status: "healthy", last_run_at: new Date(Date.now() - 12 * 60 * 1000).toISOString(), last_event_count: 64, consecutive_zeros: 0 },
    { name: "minnesotastreet", status: "healthy", last_run_at: new Date(Date.now() - 12 * 60 * 1000).toISOString(), last_event_count: 14, consecutive_zeros: 0 },
    { name: "reddit", status: "healthy", last_run_at: new Date(Date.now() - 12 * 60 * 1000).toISOString(), last_event_count: 23, consecutive_zeros: 0 },
    { name: "eddies_list", status: "unknown", last_run_at: null, last_event_count: null, consecutive_zeros: 0 },
  ],
};

async function authenticate(context) {
  const email = `demo-${Date.now()}@example.com`;
  const password = "demopass123";
  const reg = await context.request.post(`${API_BASE}/auth/register`, {
    data: { email, password },
  });
  if (!reg.ok()) {
    throw new Error(`auth/register failed: ${reg.status()}`);
  }
  const body = await reg.json();
  const token = body.access_token;
  const auth = { Authorization: `Bearer ${token}` };

  await context.request.post(`${API_BASE}/users/me/onboarding`, {
    data: { perfect_saturday: "Live music in the evening, brunch in the morning, art and outdoor markets in between." },
    headers: auth,
  });

  for (const tag of ["#LiveMusic", "#Outdoors", "#Art", "#Indie", "#Date"]) {
    await context.request.post(`${API_BASE}/users/me/interests`, {
      data: { action: "like", vibe_tag: tag },
      headers: auth,
    });
  }

  await context.addInitScript((payload) => {
    window.__authInjected = true;
    try {
      window.localStorage.setItem(
        "tof_auth",
        JSON.stringify({ token: payload.token, email: payload.email, userId: payload.userId })
      );
    } catch (e) {
      window.__authError = String(e);
    }
  }, { token, email: body.email, userId: body.user_id });
  console.log(`  authed as ${body.email}`);
}

async function capture() {
  await mkdir(OUT_DIR, { recursive: true });
  const browser = await chromium.launch();
  const context = await browser.newContext({
    viewport: { width: 1280, height: 1600 },
    deviceScaleFactor: 2,
    colorScheme: "dark",
  });

  let authedOnce = false;
  for (const shot of SHOTS) {
    if (shot.auth && !authedOnce) {
      await authenticate(context);
      authedOnce = true;
    }
    const page = await context.newPage();
    const url = `${WEB_BASE}${shot.path}`;
    console.log(`-> ${shot.name}  ${url}`);
    await page.goto(url, { waitUntil: "domcontentloaded" });
    if (shot.auth) {
      // Verify the AuthProvider picked up our injected token.
      try {
        await page.waitForSelector('header span:has-text("@")', { timeout: 5000 });
      } catch {
        const debug = await page.evaluate(() => ({
          tof_auth: window.localStorage.getItem("tof_auth"),
          injected: window.__authInjected,
          token: window.__authToken,
          err: window.__authError,
          keys: Object.keys(window.localStorage),
        }));
        console.warn(`  warn: header email not visible. debug:`, JSON.stringify(debug));
      }
    }

    if (shot.waitFor) {
      try {
        await page.waitForSelector(shot.waitFor, { timeout: 6000 });
      } catch (e) {
        console.warn(`  warn: waitFor "${shot.waitFor}" timed out — capturing anyway`);
      }
    }

    if (shot.interact === "vibes") {
      const email = `vibe-${Date.now()}@example.com`;
      try {
        await page.locator('input[type="email"]').pressSequentially(email, { delay: 10 });
        await page.locator('input[type="password"]').pressSequentially("demopass123", { delay: 10 });
        await page.waitForTimeout(150);
        await page.locator('form button[type="submit"]').click();
        await page.waitForSelector('h2:has-text("What are you into")', { timeout: 8000 });
        for (const label of ["Live Music", "Nightlife & Clubs", "Art & Museums", "Outdoors & Nature"]) {
          try {
            await page.click(`button:has-text("${label}")`, { timeout: 1500 });
          } catch {}
        }
        await page.waitForTimeout(400);
      } catch (e) {
        console.warn("  warn: vibe-picker advance failed:", e.message);
      }
    }

    if (shot.interact === "map") {
      try {
        await page.click('button:has-text("Map")');
        // Wait for Leaflet tiles to settle
        await page.waitForSelector('.leaflet-tile-loaded', { timeout: 8000 });
        await page.waitForTimeout(1200);
      } catch (e) {
        console.warn("  warn: map toggle failed:", e.message);
      }
    }

    if (shot.interact === "stubHealth") {
      // The shot is already navigated; reload after intercepting will not
      // re-trigger React fetch, so we route BEFORE navigating.
      // (We re-do the navigation here under the route override.)
      await page.route("**/health/sources", async (route) => {
        await route.fulfill({
          status: 200,
          contentType: "application/json",
          body: JSON.stringify(DEMO_HEALTH),
        });
      });
      await page.reload({ waitUntil: "domcontentloaded" });
      await page.waitForSelector('h2:has-text("Source Health")', { timeout: 5000 });
      await page.waitForSelector('table tbody tr', { timeout: 3000 });
    }

    if (shot.interact === "planner") {
      try {
        await page.locator('textarea').pressSequentially(
          "Plan a date night in the Mission this Saturday — drinks, dinner, and live music",
          { delay: 5 }
        );
        await page.waitForTimeout(150);
        await page.locator('form button[type="submit"]').click();
        await page.waitForSelector('h3:has-text("Your Plan")', { timeout: 20000 });
        await page.waitForTimeout(700);
      } catch (e) {
        console.warn("  warn: planner submit failed:", e.message);
      }
    }

    await page.waitForTimeout(shot.extraDelayMs ?? 600);

    const file = resolve(OUT_DIR, `${shot.name}.jpg`);
    await page.screenshot({ path: file, type: "jpeg", quality: 80, fullPage: false });
    console.log(`   wrote ${file}`);
    await page.close();
  }

  await browser.close();
}

capture().catch((err) => {
  console.error(err);
  process.exit(1);
});
