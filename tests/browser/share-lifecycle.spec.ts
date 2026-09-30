import { test, expect } from "@playwright/test";

test.use({ timezoneId: "America/Los_Angeles" });

const apiUrl = `http://127.0.0.1:${process.env.SHARING_E2E_API_PORT ?? 8168}`;

test("signup, private planning, explicit publication, public read, and owner revocation", async ({ page, browser, request }) => {
  const privateQuery = "Private anniversary surprise for Morgan: date night in San Francisco tomorrow";
  const email = `sharing-${Date.now()}@example.com`;
  await page.goto("/login?next=%2Fplanner");
  await page.getByLabel("Email").fill(email);
  await page.getByLabel("Password").fill("sharing-test-password");
  await page.getByRole("button", { name: "Create account", exact: true }).click();
  await expect(page.getByRole("heading", { name: "What are you into?" })).toBeVisible();
  await page.getByRole("button", { name: "Skip for now", exact: true }).click();
  await expect(page).toHaveURL(/\/planner$/);

  let publications = 0;
  page.on("request", (req) => {
    if (req.method() === "POST" && req.url() === `${apiUrl}/concierge/itinerary/share`) publications += 1;
  });
  await page.getByPlaceholder(/plan a date in the Mission/).fill(privateQuery);
  await page.getByLabel("Starting point (optional)", { exact: true }).fill("Ocean Beach");
  await page.getByLabel("Origin latitude (optional)", { exact: true }).fill("37.76");
  await page.getByLabel("Origin longitude (optional)", { exact: true }).fill("-122.509");
  await page.getByLabel("Travel mode").selectOption("walking");
  const tomorrow = new Date(Date.now() + 86400000).toLocaleDateString("en-CA", { timeZone: "America/Los_Angeles" });
  for (const [i, title, kind, minute] of [[1, "Meet at Java Beach Cafe", "meeting", "00"], [2, "Stroll the coastal trail", "walk", "20"]] as const) {
    await page.getByRole("button", { name: "Add your own stop", exact: true }).click();
    await page.getByLabel(`Stop ${i} kind`).selectOption(kind);
    await page.getByLabel(`Stop ${i} title`, { exact: true }).fill(title);
    await page.getByLabel(`Stop ${i} place`, { exact: true }).fill("Ocean Beach");
    await page.getByLabel(`Stop ${i} start (your device time zone)`, { exact: true }).fill(`${tomorrow}T16:${minute}`);
    await page.getByLabel(`Stop ${i} latitude (optional)`, { exact: true }).fill("37.76");
    await page.getByLabel(`Stop ${i} longitude (optional)`, { exact: true }).fill("-122.50");
  }
  await page.getByRole("button", { name: "Build itinerary", exact: true }).click();
  await expect(page.getByText("Sharing acceptance jazz", { exact: true })).toBeVisible();
  expect(publications).toBe(0);
  await expect(page.getByText("Added by the planner", { exact: true })).toHaveCount(2);

  const published = page.waitForResponse((res) => res.request().method() === "POST" && res.url() === `${apiUrl}/concierge/itinerary/share`);
  await page.getByRole("button", { name: "Create public link", exact: true }).click();
  const publication = await published;
  expect(publication.status()).toBe(200);
  expect(publication.request().postDataJSON()).not.toHaveProperty("query");
  const plan = await publication.json();
  expect(plan).not.toHaveProperty("query");
  expect(JSON.stringify(plan)).not.toContain(privateQuery);
  expect(Date.parse(plan.expires_at)).toBeGreaterThan(Date.now());
  expect(publications).toBe(1);
  expect(plan.origin.name).toBe("Ocean Beach");
  expect(plan.travel_mode).toBe("walking");
  expect(plan.itinerary.map((stop: { provenance: string }) => stop.provenance)).toEqual(["planner", "planner", "event"]);
  expect(plan.itinerary[0].links.tickets_url).toBeNull();
  expect(plan.itinerary[0].links.directions_url).toContain("travelmode=walking");
  expect(plan.text).toContain("Added by the planner");
  expect(plan.text).toContain("Leave by ~");

  // A separate browser has no owner token; reading a live link remains public.
  const recipient = await browser.newContext({ baseURL: test.info().project.use.baseURL });
  try {
    const publicPage = await recipient.newPage();
    await publicPage.goto(plan.share_url);
    await expect(publicPage.getByText("Sharing acceptance jazz", { exact: true })).toBeVisible();
    await expect(publicPage.getByText(privateQuery, { exact: true })).toHaveCount(0);
    await expect(publicPage.getByText("Meet at Java Beach Cafe", { exact: true })).toBeVisible();
    await expect(publicPage.getByText("Stroll the coastal trail", { exact: true })).toBeVisible();
    await expect(publicPage.getByText("Added by the planner", { exact: true })).toHaveCount(2);
    await expect(publicPage.getByText(/Leave by ~/).first()).toBeVisible();
    const publicRead = await request.get(`${apiUrl}/shared/itineraries/${plan.share_token}`);
    expect(publicRead.status()).toBe(200);
    expect(publicRead.headers()["cache-control"]).toContain("no-store");
    expect(await publicRead.json()).not.toHaveProperty("query");

    // The owner can recover the control after navigation/reload and revoke it.
    await page.goto("/shared-plans");
    await page.reload();
    await expect(page.getByRole("link", { name: plan.title, exact: true })).toBeVisible();
    await page.getByRole("button", { name: "Revoke link", exact: true }).click();
    await expect(page.getByText("Revoked", { exact: true })).toBeVisible();
    const unavailable = await request.get(`${apiUrl}/shared/itineraries/${plan.share_token}`);
    expect(unavailable.status()).toBe(404);
    expect(unavailable.headers()["cache-control"]).toContain("no-store");
    await publicPage.reload();
    await expect(publicPage.getByText("Sharing acceptance jazz", { exact: true })).toHaveCount(0);
    await expect(publicPage.getByText(/unavailable|expired|revoked|not found/i).first()).toBeVisible();
  } finally {
    await recipient.close();
  }
});
