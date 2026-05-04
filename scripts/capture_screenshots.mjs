/**
 * Capture UI screenshots for README using Playwright.
 *
 * Assumes:
 *   - Web is running on http://127.0.0.1:3030
 *   - API is running on http://127.0.0.1:8000
 *   - Database is seeded (npm run seed at backend)
 *
 * Output: docs/screenshots/{name}.png
 */
import { chromium } from "playwright";
import { mkdir } from "node:fs/promises";
import { resolve, dirname } from "node:path";
import { fileURLToPath } from "node:url";

const __dirname = dirname(fileURLToPath(import.meta.url));
const OUT_DIR = resolve(__dirname, "../docs/screenshots");
const WEB_BASE = process.env.WEB_BASE || "http://127.0.0.1:3030";
const API_BASE = process.env.API_BASE || "http://127.0.0.1:8000";

const SHOTS = [
  { name: "01-home", path: "/", waitFor: 'h2:has-text("fragmented")' },
  { name: "02-explore", path: "/explore", waitFor: 'h3', extraDelayMs: 1500 },
  { name: "03-planner", path: "/planner", waitFor: 'button:has-text("Build itinerary")', interact: "planner" },
  { name: "04-onboarding-vibes", path: "/login", waitFor: 'h2', interact: "vibes" },
  { name: "05-recommendations", path: "/recommendations", waitFor: 'h2', auth: true, extraDelayMs: 1500 },
];

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
    window.localStorage.setItem(
      "bae_auth",
      JSON.stringify({ token: payload.token, email: payload.email, userId: payload.userId })
    );
  }, { token, email: body.email, userId: body.user_id });
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
    if (shot.auth) {
      // 1) Land on /explore so AuthProvider mounts and primes apiClient from localStorage.
      // 2) Wait for authed nav (the email span proves token is set).
      // 3) Navigate via Next.js Link (client-side routing) so AuthProvider stays mounted
      //    and apiClient still has the token when the protected page mounts.
      await page.goto(`${WEB_BASE}/explore`, { waitUntil: "domcontentloaded" });
      try {
        await page.waitForSelector('header span:has-text("@")', { timeout: 5000 });
      } catch {}
      await page.waitForTimeout(300);
      const linkLabel = shot.path.startsWith("/recommendations") ? "For You" : null;
      if (linkLabel) {
        await page.click(`nav a:has-text("${linkLabel}")`);
      } else {
        await page.goto(url, { waitUntil: "domcontentloaded" });
      }
    } else {
      await page.goto(url, { waitUntil: "domcontentloaded" });
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

    const file = resolve(OUT_DIR, `${shot.name}.png`);
    await page.screenshot({ path: file, fullPage: false });
    console.log(`   wrote ${file}`);
    await page.close();
  }

  await browser.close();
}

capture().catch((err) => {
  console.error(err);
  process.exit(1);
});
