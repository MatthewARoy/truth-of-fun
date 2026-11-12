import { readFile } from "node:fs/promises";
import { test, expect, type Page } from "@playwright/test";
import { API, SESSION, signInFixture, storedSession } from "./helpers";

const LOGIN_SHAPED = { access_token: "new-token", token_type: "bearer", user_id: 1, email: "me@example.test" };
const NEUTRAL = /If an account exists for that email address, a password reset link is on its way/;
const alert = (page: Page) => page.getByRole("main").getByRole("alert");

test("sign-in form: labelled inputs with autocomplete, pressed-state chips, and a forgot-password link", async ({ page }) => {
  await page.route(`${API}/auth/register`, (route) => route.fulfill({ json: LOGIN_SHAPED }));
  await page.goto("/login");
  // Sign-up mode by default.
  await expect(page.getByLabel("Email")).toHaveAttribute("autocomplete", "email");
  await expect(page.getByLabel("Password")).toHaveAttribute("autocomplete", "new-password");
  await expect(page.getByRole("link", { name: "Forgot password?" })).toHaveCount(0);

  await page.getByRole("button", { name: "Sign in", exact: true }).click();
  await expect(page.getByLabel("Password")).toHaveAttribute("autocomplete", "current-password");
  await page.getByRole("link", { name: "Forgot password?" }).click();
  await expect(page).toHaveURL(/\/forgot-password$/);

  // Interest chips expose their state.
  await page.goto("/login");
  await page.getByLabel("Email").fill("me@example.test");
  await page.getByLabel("Password").fill("a-long-test-password");
  await page.getByRole("button", { name: "Create account", exact: true }).click();
  const comedy = page.getByRole("button", { name: /Comedy/ });
  await expect(comedy).toHaveAttribute("aria-pressed", "false");
  await comedy.click();
  await expect(comedy).toHaveAttribute("aria-pressed", "true");
});

test("forgot password always shows the same neutral confirmation", async ({ page }) => {
  const bodies: unknown[] = [];
  await page.route(`${API}/auth/password-reset/request`, (route) => {
    bodies.push(route.request().postDataJSON());
    expect(route.request().headers().authorization).toBeUndefined();
    return route.fulfill({ status: 202, json: { detail: "If that address has an account, a reset link has been sent." } });
  });
  await page.goto("/forgot-password");
  await expect(page.getByRole("heading", { level: 1, name: "Reset your password" })).toBeVisible();
  const email = page.getByLabel("Email");
  await expect(email).toHaveAttribute("autocomplete", "email");

  const confirmations: string[] = [];
  for (const address of ["known@example.test", "nobody@example.test"]) {
    await email.fill(address);
    await page.getByRole("button", { name: "Send reset link" }).click();
    const notice = page.getByRole("status").filter({ hasText: NEUTRAL });
    await expect(notice).toBeVisible();
    confirmations.push(await notice.innerText());
    // The confirmation does not echo the address or say whether it exists.
    expect(confirmations.at(-1)).not.toContain(address);
    await page.getByRole("button", { name: "Use a different email address" }).click();
  }
  expect(confirmations[0]).toBe(confirmations[1]);
  expect(bodies).toEqual([{ email: "known@example.test" }, { email: "nobody@example.test" }]);
  await expect(page.getByRole("link", { name: "Back to sign in" })).toHaveAttribute("href", "/login");
});

test("forgot password reports a failed request instead of claiming an email was sent", async ({ page }) => {
  await page.route(`${API}/auth/password-reset/request`, (route) =>
    route.fulfill({ status: 429, json: { detail: "Too many attempts. Try again in a minute." } }));
  await page.goto("/forgot-password");
  await page.getByLabel("Email").fill("me@example.test");
  await page.getByRole("button", { name: "Send reset link" }).click();
  await expect(alert(page)).toHaveText("Too many attempts. Try again in a minute.");
  await expect(page.getByText(NEUTRAL)).toHaveCount(0);
});

test("reset password: validates, explains a bad link, then signs the user in", async ({ page }) => {
  const bodies: Array<{ token: string; new_password: string }> = [];
  await page.route(`${API}/auth/password-reset/confirm`, (route) => {
    const body = route.request().postDataJSON();
    bodies.push(body);
    if (body.token !== "good-token") {
      return route.fulfill({ status: 400, json: { detail: "This reset link is invalid or has expired." } });
    }
    if (body.new_password === "weak-but-long-enough") {
      return route.fulfill({ status: 422, json: { detail: [
        { loc: ["body", "new_password"], msg: "Value error, Password must be at most 72 UTF-8 bytes.", type: "value_error" },
      ] } });
    }
    return route.fulfill({ json: LOGIN_SHAPED });
  });
  await page.route((url) => url.href.startsWith(`${API}/events?`), (route) => route.fulfill({ json: [] }));
  await page.route(`${API}/regions`, (route) => route.fulfill({ json: { regions: [] } }));

  // No token in the link.
  await page.goto("/reset-password");
  await expect(alert(page)).toContainText("This reset link is incomplete");
  await expect(page.getByRole("link", { name: "Request a new reset link" })).toHaveAttribute("href", "/forgot-password");
  await expect(page.getByLabel("New password")).toHaveCount(0);

  // Expired or unknown token.
  await page.goto("/reset-password?token=stale-token");
  const password = page.getByLabel("New password", { exact: true });
  const confirmation = page.getByLabel("Confirm new password");
  await expect(password).toHaveAttribute("autocomplete", "new-password");
  await expect(confirmation).toHaveAttribute("autocomplete", "new-password");
  await password.fill("a-brand-new-password");
  await confirmation.fill("a-brand-new-password");
  await page.getByRole("button", { name: "Set new password" }).click();
  await expect(alert(page)).toContainText("This reset link is invalid or has expired.");
  await expect(alert(page).getByRole("link", { name: "Request a new link" })).toHaveAttribute("href", "/forgot-password");
  expect(await storedSession(page)).toBeNull();

  await page.goto("/reset-password?token=good-token");
  // Mismatch is caught before anything is sent.
  await password.fill("a-brand-new-password");
  await confirmation.fill("a-different-password");
  await page.getByRole("button", { name: "Set new password" }).click();
  await expect(alert(page)).toHaveText("The two passwords do not match.");
  expect(bodies).toHaveLength(1);

  // A 422 from the API is readable.
  await password.fill("weak-but-long-enough");
  await confirmation.fill("weak-but-long-enough");
  await page.getByRole("button", { name: "Set new password" }).click();
  await expect(alert(page)).toHaveText("new_password: Password must be at most 72 UTF-8 bytes.");

  await password.fill("a-brand-new-password");
  await confirmation.fill("a-brand-new-password");
  await page.getByRole("button", { name: "Set new password" }).click();
  await expect(page).toHaveURL(/\/explore$/);
  expect(bodies.at(-1)).toEqual({ token: "good-token", new_password: "a-brand-new-password" });
  // Signed in with the token from the response.
  expect(await storedSession(page)).toEqual({ token: "new-token", email: "me@example.test", userId: 1 });
  await expect(page.getByRole("button", { name: "Log out" })).toBeVisible();
  await expect(page.getByRole("navigation", { name: "Main" }).getByRole("link", { name: "Account" })).toBeVisible();
});

test("account page asks anonymous visitors to sign in and is linked from the nav only when signed in", async ({ page }) => {
  await page.goto("/account");
  await expect(page.getByText("Sign in to manage your account.")).toBeVisible();
  await expect(page.getByRole("main").getByRole("link", { name: "Sign in" })).toHaveAttribute("href", "/login?next=%2Faccount");
  await expect(page.getByRole("navigation", { name: "Main" }).getByRole("link", { name: "Account" })).toHaveCount(0);
});

async function mockProfile(page: Page, preferred = ["#Comedy", "#custom-tag"]) {
  await page.route(`${API}/users/me`, (route) => route.fulfill({
    json: { user_id: 1, preferred_vibes: preferred, saved_event_ids: [], vibe_scores: {} },
  }));
}

test("account: interests can be changed later, as sign-up promises", async ({ page }) => {
  await signInFixture(page);
  await mockProfile(page);
  let saved: { preferred_vibes: string[] } | undefined;
  await page.route(`${API}/users/me/preferences`, (route) => {
    expect(route.request().method()).toBe("PUT");
    saved = route.request().postDataJSON();
    return route.fulfill({ json: { user_id: 1, saved_event_ids: [], preferred_vibes: saved!.preferred_vibes } });
  });
  await page.goto("/account");
  await expect(page.getByRole("heading", { level: 1, name: "Account" })).toBeVisible();
  await expect(page.getByRole("main")).toContainText("Signed in as me@example.test");
  await page.getByRole("navigation", { name: "Main" }).getByRole("link", { name: "Account" }).click();
  await expect(page).toHaveURL(/\/account$/);

  const interests = page.getByRole("group", { name: "Interests" });
  await expect(interests.getByRole("button", { name: /Comedy/ })).toHaveAttribute("aria-pressed", "true");
  await expect(interests.getByRole("button", { name: /Live Music/ })).toHaveAttribute("aria-pressed", "false");
  // An interest learned elsewhere is shown, not silently dropped on save.
  await expect(interests.getByRole("button", { name: "#custom-tag" })).toHaveAttribute("aria-pressed", "true");

  await interests.getByRole("button", { name: /Live Music/ }).click();
  await interests.getByRole("button", { name: /Comedy/ }).click();
  await page.getByRole("button", { name: "Save interests" }).click();
  await expect(page.getByText("Interests saved.")).toBeVisible();
  expect(saved).toEqual({ preferred_vibes: ["#custom-tag", "#LiveMusic"] });
});

test("account: change password rejects a wrong current password, then adopts the new token", async ({ page }) => {
  await signInFixture(page);
  await mockProfile(page);
  const bodies: unknown[] = [];
  await page.route(`${API}/users/me/password`, (route) => {
    const body = route.request().postDataJSON();
    bodies.push({ ...body, auth: route.request().headers().authorization });
    if (body.current_password !== "my-current-password") {
      return route.fulfill({ status: 400, json: { detail: "That password is not correct." } });
    }
    return route.fulfill({ json: LOGIN_SHAPED });
  });
  const exportAuth: Array<string | undefined> = [];
  await page.route(`${API}/users/me/export`, (route) => {
    exportAuth.push(route.request().headers().authorization);
    return route.fulfill({ json: {} });
  });
  await page.goto("/account");

  const form = page.locator("form").filter({ has: page.getByRole("button", { name: "Change password" }) });
  const current = form.getByLabel("Current password");
  const next = form.getByLabel("New password", { exact: true });
  const confirmation = form.getByLabel("Confirm new password");
  await expect(current).toHaveAttribute("autocomplete", "current-password");
  await expect(next).toHaveAttribute("autocomplete", "new-password");
  await expect(confirmation).toHaveAttribute("autocomplete", "new-password");

  // Client-side checks send nothing.
  await current.fill("my-current-password");
  await next.fill("a-brand-new-password");
  await confirmation.fill("something-else-entirely");
  await form.getByRole("button", { name: "Change password" }).click();
  await expect(form.getByRole("alert")).toHaveText("The two new passwords do not match.");
  expect(bodies).toHaveLength(0);

  // Wrong current password: a 400 is an error on the form; the session stays.
  await current.fill("not-my-password");
  await confirmation.fill("a-brand-new-password");
  await form.getByRole("button", { name: "Change password" }).click();
  await expect(form.getByRole("alert")).toHaveText("That password is not correct.");
  await expect(page).toHaveURL(/\/account$/);
  expect((await storedSession(page)).token).toBe(SESSION.token);

  await current.fill("my-current-password");
  await form.getByRole("button", { name: "Change password" }).click();
  await expect(form.getByRole("status")).toHaveText("Password changed. Other devices have been signed out.");
  expect(bodies.at(-1)).toEqual({
    current_password: "my-current-password", new_password: "a-brand-new-password", auth: "Bearer fixture-token",
  });
  await expect(current).toHaveValue("");
  await expect(next).toHaveValue("");

  // The old token is dead; the new one is stored and used from now on.
  expect(await storedSession(page)).toEqual({ token: "new-token", email: "me@example.test", userId: 1 });
  await page.getByRole("button", { name: "Download my data" }).click();
  await expect.poll(() => exportAuth).toEqual(["Bearer new-token"]);
  await page.reload();
  await expect(page.getByRole("main")).toContainText("Signed in as me@example.test");
});

test("account: download my data saves a JSON file", async ({ page }) => {
  await signInFixture(page);
  await mockProfile(page);
  const exported = { exported_at: "2026-11-12T00:00:00Z", account: { email: "me@example.test" }, saved_events: [{ event_id: 7, title: "Saved show" }] };
  await page.route(`${API}/users/me/export`, (route) => route.fulfill({ json: exported }));
  await page.goto("/account");
  const [download] = await Promise.all([
    page.waitForEvent("download"),
    page.getByRole("button", { name: "Download my data" }).click(),
  ]);
  expect(download.suggestedFilename()).toMatch(/^truth-of-fun-data-\d{4}-\d{2}-\d{2}\.json$/);
  expect(JSON.parse(await readFile(await download.path(), "utf8"))).toEqual(exported);
  await expect(page.getByText("Your data file has been downloaded.")).toBeVisible();
});

test("account: sign out everywhere revokes tokens and signs this browser out", async ({ page }) => {
  await signInFixture(page);
  await mockProfile(page);
  const calls: Array<string | undefined> = [];
  await page.route(`${API}/auth/logout`, (route) => {
    expect(route.request().method()).toBe("POST");
    calls.push(route.request().headers().authorization);
    return route.fulfill({ status: 204 });
  });
  await page.goto("/account");
  await page.getByRole("button", { name: "Sign out everywhere" }).click();
  await expect(page).toHaveURL(/\/$/);
  expect(calls).toEqual(["Bearer fixture-token"]);
  expect(await storedSession(page)).toBeNull();
  await expect(page.getByRole("navigation", { name: "Main" }).getByRole("link", { name: "Sign in" })).toBeVisible();
});

test("account: delete needs the password and an explicit confirmation, then signs out and goes home", async ({ page }) => {
  await signInFixture(page);
  await mockProfile(page);
  const bodies: unknown[] = [];
  await page.route(`${API}/users/me/delete`, (route) => {
    expect(route.request().method()).toBe("POST");
    const body = route.request().postDataJSON();
    bodies.push(body);
    return body.password === "my-current-password"
      ? route.fulfill({ status: 204 })
      : route.fulfill({ status: 400, json: { detail: "That password is not correct." } });
  });
  await page.goto("/account");

  const form = page.locator("form").filter({ has: page.getByRole("button", { name: "Delete my account" }) });
  const submit = form.getByRole("button", { name: "Delete my account" });
  const password = form.getByLabel("Enter your password to confirm");
  const confirm = form.getByLabel("I understand that my account and its data will be permanently deleted.");

  // Neither the password alone nor the checkbox alone is enough.
  await expect(submit).toBeDisabled();
  await password.fill("not-my-password");
  await expect(submit).toBeDisabled();
  await password.fill("");
  await confirm.check();
  await expect(submit).toBeDisabled();

  await password.fill("not-my-password");
  await expect(submit).toBeEnabled();
  await submit.click();
  await expect(form.getByRole("alert")).toHaveText("That password is not correct.");
  // Still signed in, still on the page.
  await expect(page).toHaveURL(/\/account$/);
  expect((await storedSession(page)).token).toBe(SESSION.token);

  await password.fill("my-current-password");
  await submit.click();
  await expect(page).toHaveURL(/\/$/);
  await expect(page.getByRole("heading", { level: 1, name: /something fun to do/i })).toBeVisible();
  expect(bodies).toEqual([{ password: "not-my-password" }, { password: "my-current-password" }]);
  expect(await storedSession(page)).toBeNull();
  await expect(page.getByRole("navigation", { name: "Main" }).getByRole("link", { name: "Sign in" })).toBeVisible();
  await expect(page.getByRole("button", { name: "Log out" })).toHaveCount(0);
});
