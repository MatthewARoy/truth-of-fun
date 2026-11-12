import assert from "node:assert/strict";
import { afterEach, test } from "node:test";
import { ApiClientError, TruthOfFunApiClient } from "../dist/client.js";

const originalFetch = globalThis.fetch;
afterEach(() => { globalThis.fetch = originalFetch; });
const client = () => new TruthOfFunApiClient("http://stub.invalid");

test("permanent HTTP failures do not retry", async () => {
  for (const status of [400, 401, 403, 404, 422]) {
    let calls = 0;
    globalThis.fetch = async () => { calls++; return new Response("{}", { status }); };
    await assert.rejects(client().getEvents(), (error) => error instanceof ApiClientError && error.status === status);
    assert.equal(calls, 1, `HTTP ${status}`);
  }
});

test("Retry-After exceeding the deadline never causes an early retry", async () => {
  for (const retryAfter of ["60", new Date(Date.now() + 60_000).toUTCString()]) {
    let calls = 0;
    globalThis.fetch = async () => {
      calls++;
      return new Response("{}", { status: 429, headers: { "Retry-After": retryAfter } });
    };
    await assert.rejects(client().getEvents({}, { timeoutMs: 100 }), { status: 429 });
    assert.equal(calls, 1);
  }
});

test("transient GET failure waits before retrying and can recover", async () => {
  const calls = [];
  globalThis.fetch = async () => {
    calls.push(Date.now());
    return calls.length === 1 ? new Response("{}", { status: 503 }) : new Response("[]");
  };
  assert.deepEqual(await client().getEvents(), []);
  assert.equal(calls.length, 2);
  assert.ok(calls[1] - calls[0] >= 450, "must back off rather than immediately doubling load");
});

test("abort during retry backoff prevents another request", async () => {
  const controller = new AbortController();
  let calls = 0;
  globalThis.fetch = async () => {
    calls++;
    setTimeout(() => controller.abort(), 10);
    return new Response("{}", { status: 503 });
  };
  await assert.rejects(client().getEvents({}, { signal: controller.signal }), { name: "AbortError" });
  assert.equal(calls, 1);
});

test("deadline aborts a stalled request without retrying", async () => {
  let calls = 0;
  globalThis.fetch = async (_url, { signal }) => {
    calls++;
    return new Promise((_resolve, reject) => {
      signal.addEventListener("abort", () => reject(signal.reason), { once: true });
    });
  };
  await assert.rejects(client().getEvents({}, { timeoutMs: 20 }), { name: "TimeoutError" });
  assert.equal(calls, 1);
});

test("writes never retry after transient failures", async () => {
  let calls = 0;
  globalThis.fetch = async () => { calls++; return new Response("{}", { status: 503 }); };
  await assert.rejects(client().createFolder("Saturday"), { status: 503 });
  assert.equal(calls, 1);
});

test("explicit preferences use the replacement endpoint and preserve all selected tags", async () => {
  const selected = ["#LiveMusic", "#Comedy", "#Nightlife", "#FoodAndDrink"];
  globalThis.fetch = async (url, init) => {
    assert.equal(url, "http://stub.invalid/users/me/preferences");
    assert.equal(init.method, "PUT");
    assert.deepEqual(JSON.parse(init.body), { preferred_vibes: selected });
    return new Response(JSON.stringify({ user_id: 1, saved_event_ids: [], preferred_vibes: selected }));
  };
  assert.deepEqual((await client().setPreferences({ preferred_vibes: selected })).preferred_vibes, selected);
});

test("public share serializes selected stops and expiry without a legacy private prompt", async () => {
  globalThis.fetch = async (url, init) => {
    assert.equal(url, "http://stub.invalid/concierge/itinerary/share");
    assert.equal(init.method, "POST");
    assert.deepEqual(JSON.parse(init.body), {
      intent: "date_night", expires_in_days: 7,
      stops: [{ event_id: 42, kind: "main_event", travel_buffer_minutes_before: 0 }],
    });
    return new Response(JSON.stringify({ share_token: "new-token", expires_at: "2026-10-06T00:00:00Z" }));
  };
  // Runtime callers can still pass old fields despite the updated TS type.
  await client().shareItinerary({
    query: "Private personal details must not be sent", intent: "date_night", expires_in_days: 7,
    stops: [{ event_id: 42, kind: "main_event", travel_buffer_minutes_before: 0 }],
  });
});

test("owner list and public detail use no-store and support abort signals", async () => {
  const authenticated = client();
  authenticated.setToken("owner-token");
  const controller = new AbortController();
  let calls = 0;
  globalThis.fetch = async (url, init) => {
    calls++;
    assert.equal(init.cache, "no-store");
    assert.equal(init.headers.Authorization, "Bearer owner-token");
    assert.ok(init.signal instanceof AbortSignal);
    assert.equal(url, calls === 1 ? "http://stub.invalid/users/me/itineraries?limit=25&offset=50" : "http://stub.invalid/shared/itineraries/token%2Fpart");
    return new Response("[]");
  };
  assert.deepEqual(await authenticated.getMyItineraries(25, 50, { signal: controller.signal }), []);
  await authenticated.getSharedItinerary("token/part", { signal: controller.signal });
});

test("revoking a share handles empty 204 responses and never retries a failed delete", async () => {
  let calls = 0;
  globalThis.fetch = async (url, init) => {
    calls++;
    assert.equal(url, "http://stub.invalid/users/me/itineraries/token%2Fpart");
    assert.equal(init.method, "DELETE");
    return calls === 1 ? new Response(null, { status: 204 }) : new Response("{}", { status: 503 });
  };
  assert.equal(await client().revokeItinerary("token/part"), undefined);
  await assert.rejects(client().revokeItinerary("token/part"), { status: 503 });
  assert.equal(calls, 2);
});

test("mixed-stop publication preserves explicitly public origin/mode and excludes private query", async () => {
  const stop = { kind: "meeting", user_stop: { kind: "meeting", title: "Meet here", place: { name: "Ocean Beach" }, start_at: "2026-10-01T17:00:00-07:00" } };
  globalThis.fetch = async (_url, init) => {
    assert.deepEqual(JSON.parse(init.body), { stops: [stop], origin: { name: "Ocean Beach" }, travel_mode: "walking" });
    return new Response("{}");
  };
  await client().shareItinerary({ query: "private", stops: [stop], origin: { name: "Ocean Beach" }, travel_mode: "walking" });
});

// --- Launch-readiness coverage ------------------------------------------------

const json = (body, init) => new Response(JSON.stringify(body), init);
const AUTH = { access_token: "new-token", token_type: "bearer", user_id: 1, email: "me@example.test" };

test("FastAPI validation errors are flattened into a readable message", async () => {
  globalThis.fetch = async () => json({ detail: [
    { loc: ["body", "password"], msg: "String should have at least 12 characters", type: "string_too_short" },
    { loc: ["body", "email"], msg: "Value error, value is not a valid email address", type: "value_error" },
    { loc: ["query", "limit"], msg: "Input should be less than or equal to 100", type: "less_than_equal" },
  ] }, { status: 422 });
  await assert.rejects(client().register({ email: "x", password: "short" }), (error) => {
    assert.ok(error instanceof ApiClientError);
    assert.equal(error.status, 422);
    assert.equal(
      error.message,
      "password: String should have at least 12 characters; email: value is not a valid email address; "
      + "limit: Input should be less than or equal to 100"
    );
    assert.ok(Array.isArray(error.payload.detail), "the raw payload stays available");
    return true;
  });
});

test("string details pass through and unusable payloads fall back to the status", async () => {
  const cases = [
    [{ detail: "Token has expired." }, 401, "Token has expired."],
    [{ detail: [] }, 422, "Request failed: 422"],
    [{ detail: [{ loc: ["body"], msg: "Field required" }] }, 422, "Field required"],
    [{ detail: [{ nonsense: true }] }, 422, "Request failed: 422"],
    [{ detail: { code: 7 } }, 400, "Request failed: 400"],
    [{ message: "other shape" }, 400, "Request failed: 400"],
  ];
  for (const [body, status, message] of cases) {
    globalThis.fetch = async () => json(body, { status });
    await assert.rejects(client().createFolder("x"), { message, status });
  }
  globalThis.fetch = async () => new Response("<html>bad gateway</html>", { status: 400 });
  await assert.rejects(client().createFolder("x"), { message: "Request failed: 400" });
});

test("Content-Type is sent only with a body, so reads avoid a CORS preflight", async () => {
  const seen = [];
  globalThis.fetch = async (url, init) => {
    seen.push({ url, method: init.method ?? "GET", headers: init.headers });
    return init.method === "DELETE" ? new Response(null, { status: 204 }) : json({});
  };
  const api = client();
  await api.getEvents({ q: "jazz" });
  await api.getRegions();
  await api.revokeItinerary("abc");
  await api.createFolderInvite(7); // POST without a body
  await api.createFolder("Saturday");
  assert.deepEqual(seen.map((call) => "Content-Type" in call.headers), [false, false, false, false, true]);
  assert.equal(seen[4].headers["Content-Type"], "application/json");
  // Anonymous bodyless reads carry no non-safelisted header at all.
  assert.deepEqual(seen[0].headers, {});
});

test("every interpolated id or token is encoded as a single path segment", async () => {
  const urls = [];
  globalThis.fetch = async (url, init) => {
    urls.push(url);
    return init.method === "DELETE" ? new Response(null, { status: 204 }) : json({});
  };
  const api = client();
  const evil = "a/b?c#d";
  await api.getSharedFolder(evil);
  await api.acceptFolderInvite(evil);
  await api.revokeFolderInvite(7, evil);
  await api.getSharedItinerary(evil);
  await api.revokeItinerary(evil);
  // Ids are typed as numbers, but a runtime string must not escape its segment.
  await api.getEvent("1/../admin");
  await api.getFolder("7/items");
  await api.revokeAgentToken("3?x=1");
  const enc = "a%2Fb%3Fc%23d";
  assert.deepEqual(urls, [
    `http://stub.invalid/shared/folders/${enc}`,
    `http://stub.invalid/folders/invites/${enc}/accept`,
    `http://stub.invalid/folders/7/invites/${enc}`,
    `http://stub.invalid/shared/itineraries/${enc}`,
    `http://stub.invalid/users/me/itineraries/${enc}`,
    "http://stub.invalid/events/1%2F..%2Fadmin",
    "http://stub.invalid/folders/7%2Fitems",
    "http://stub.invalid/users/me/tokens/3%3Fx%3D1",
  ]);
  assert.equal(api.eventCalendarUrl(42), "http://stub.invalid/events/42/calendar.ics");
});

test("a relative base URL is preserved for same-origin deployments", async () => {
  const urls = [];
  globalThis.fetch = async (url) => { urls.push(url); return json([]); };
  const api = new TruthOfFunApiClient("/api/");
  await api.getEvents({ region: "east_bay", city: "Oakland", is_free: true });
  assert.deepEqual(urls, ["/api/events?region=east_bay&city=Oakland&is_free=true"]);
  assert.equal(api.eventCalendarUrl(5), "/api/events/5/calendar.ics");
  assert.equal(api.getBaseUrl(), "/api");
});

test("events query serializes the new filters and omits unset ones", async () => {
  let seen;
  globalThis.fetch = async (url) => { seen = new URL(url); return json([]); };
  await client().getEventsPage({
    region: "north_bay", city: "San Rafael", is_free: true, q: undefined, category: undefined,
    start_at: "2026-11-14T08:00:00.000Z", end_at: "2026-11-15T08:00:00.000Z",
    lat: 37.8, lng: -122.27, radius_miles: 5, sort_by: "distance",
  });
  assert.equal(seen.pathname, "/events");
  assert.deepEqual(Object.fromEntries(seen.searchParams), {
    region: "north_bay", city: "San Rafael", is_free: "true",
    start_at: "2026-11-14T08:00:00.000Z", end_at: "2026-11-15T08:00:00.000Z",
    lat: "37.8", lng: "-122.27", radius_miles: "5", sort_by: "distance",
  });
});

test("GET /regions returns the region list", async () => {
  const body = { regions: [{ id: "east_bay", label: "East Bay", upcoming_count: 412, cities: [{ name: "Oakland", upcoming_count: 230 }] }] };
  globalThis.fetch = async (url, init) => {
    assert.equal(url, "http://stub.invalid/regions");
    assert.equal(init.method, undefined);
    return json(body);
  };
  assert.deepEqual(await client().getRegions(), body);
});

test("onUnauthorized fires once for a 401 on an authenticated request and the call still rejects", async () => {
  const fired = [];
  const api = new TruthOfFunApiClient("http://stub.invalid", { onUnauthorized: (error) => fired.push(error) });
  api.setToken("stale-token");
  let calls = 0;
  globalThis.fetch = async () => { calls++; return json({ detail: "Token has expired." }, { status: 401 }); };
  await assert.rejects(api.listFolders(), { status: 401, message: "Token has expired." });
  assert.equal(calls, 1, "a 401 is never retried");
  assert.equal(fired.length, 1);
  assert.ok(fired[0] instanceof ApiClientError);
  assert.equal(fired[0].status, 401);
});

test("onUnauthorized does not fire without a token, for other statuses, or when the handler is cleared", async () => {
  let fired = 0;
  const api = client();
  api.setUnauthorizedHandler(() => { fired++; });
  globalThis.fetch = async () => json({ detail: "Not authenticated" }, { status: 401 });
  await assert.rejects(api.listFolders(), { status: 401 }); // anonymous visitor
  api.setToken("token");
  globalThis.fetch = async () => json({ detail: "Forbidden" }, { status: 403 });
  await assert.rejects(api.listFolders(), { status: 403 });
  globalThis.fetch = async () => json({ detail: "Invalid token." }, { status: 401 });
  api.setUnauthorizedHandler(null);
  await assert.rejects(api.listFolders(), { status: 401 });
  assert.equal(fired, 0);
});

test("failed sign-in, sign-up and reset attempts never fire onUnauthorized or send the old token", async () => {
  let fired = 0;
  const api = new TruthOfFunApiClient("http://stub.invalid", { onUnauthorized: () => { fired++; } });
  api.setToken("existing-session");
  const paths = [];
  globalThis.fetch = async (url, init) => {
    paths.push(new URL(url).pathname);
    assert.equal(init.headers.Authorization, undefined, "credential endpoints are anonymous");
    return json({ detail: "Invalid credentials." }, { status: 401 });
  };
  await assert.rejects(api.login({ email: "a@b.test", password: "wrong" }), { status: 401, message: "Invalid credentials." });
  await assert.rejects(api.register({ email: "a@b.test", password: "wrong" }), { status: 401 });
  await assert.rejects(api.requestPasswordReset("a@b.test"), { status: 401 });
  await assert.rejects(api.confirmPasswordReset({ token: "t", new_password: "p" }), { status: 401 });
  assert.deepEqual(paths, ["/auth/login", "/auth/register", "/auth/password-reset/request", "/auth/password-reset/confirm"]);
  assert.equal(fired, 0);
  assert.equal(api.getToken(), "existing-session");
});

test("a 401 for a token that was already replaced does not sign out the new session", async () => {
  let fired = 0;
  const api = new TruthOfFunApiClient("http://stub.invalid", { onUnauthorized: () => { fired++; } });
  api.setToken("old-token");
  globalThis.fetch = async () => {
    api.setToken("fresh-token"); // the user signed in again while this was in flight
    return json({ detail: "Token has expired." }, { status: 401 });
  };
  await assert.rejects(api.listFolders(), { status: 401 });
  assert.equal(fired, 0);
});

test("a throwing onUnauthorized handler cannot mask the 401", async () => {
  const api = new TruthOfFunApiClient("http://stub.invalid", { onUnauthorized: () => { throw new Error("boom"); } });
  api.setToken("stale");
  globalThis.fetch = async () => json({ detail: "Invalid token." }, { status: 401 });
  await assert.rejects(api.getMyProfile(), { status: 401, message: "Invalid token." });
});

test("password reset request and confirm follow the contract", async () => {
  const calls = [];
  globalThis.fetch = async (url, init) => {
    calls.push({ path: new URL(url).pathname, method: init.method, body: JSON.parse(init.body) });
    return calls.length === 1
      ? json({ detail: "If that address has an account, a reset link is on its way." }, { status: 202 })
      : json(AUTH);
  };
  const api = client();
  assert.deepEqual(await api.requestPasswordReset("me@example.test"), {
    detail: "If that address has an account, a reset link is on its way.",
  });
  assert.deepEqual(await api.confirmPasswordReset({ token: "reset-token", new_password: "a-long-new-password", extra: "dropped" }), AUTH);
  assert.deepEqual(calls, [
    { path: "/auth/password-reset/request", method: "POST", body: { email: "me@example.test" } },
    { path: "/auth/password-reset/confirm", method: "POST", body: { token: "reset-token", new_password: "a-long-new-password" } },
  ]);
  globalThis.fetch = async () => json({ detail: "This reset link is invalid or has expired." }, { status: 400 });
  await assert.rejects(api.confirmPasswordReset({ token: "bad", new_password: "a-long-new-password" }), {
    status: 400, message: "This reset link is invalid or has expired.",
  });
});

test("account endpoints: change password, logout everywhere, export, delete", async () => {
  const calls = [];
  const api = client();
  api.setToken("session-token");
  globalThis.fetch = async (url, init) => {
    const path = new URL(url).pathname;
    calls.push({ path, method: init.method ?? "GET", body: init.body ? JSON.parse(init.body) : null, auth: init.headers.Authorization });
    if (path === "/users/me/password") return json(AUTH);
    if (path === "/users/me/export") return json({ user: { email: "me@example.test" }, saved_events: [] });
    return new Response(null, { status: 204 });
  };
  assert.deepEqual(await api.changePassword({ current_password: "old-password-123", new_password: "new-password-1234" }), AUTH);
  assert.equal(await api.logoutEverywhere(), undefined);
  assert.deepEqual(await api.exportMyData(), { user: { email: "me@example.test" }, saved_events: [] });
  assert.equal(await api.deleteAccount({ password: "old-password-123" }), undefined);
  assert.deepEqual(calls, [
    { path: "/users/me/password", method: "POST", body: { current_password: "old-password-123", new_password: "new-password-1234" }, auth: "Bearer session-token" },
    { path: "/auth/logout", method: "POST", body: null, auth: "Bearer session-token" },
    { path: "/users/me/export", method: "GET", body: null, auth: "Bearer session-token" },
    { path: "/users/me/delete", method: "POST", body: { password: "old-password-123" }, auth: "Bearer session-token" },
  ]);
});

test("a wrong current password is a 400 that does not sign the user out; logout with a dead token stays quiet", async () => {
  let fired = 0;
  const api = new TruthOfFunApiClient("http://stub.invalid", { onUnauthorized: () => { fired++; } });
  api.setToken("session-token");
  globalThis.fetch = async () => json({ detail: "Current password is incorrect." }, { status: 400 });
  await assert.rejects(api.changePassword({ current_password: "nope", new_password: "new-password-1234" }), {
    status: 400, message: "Current password is incorrect.",
  });
  await assert.rejects(api.deleteAccount({ password: "nope" }), { status: 400 });
  globalThis.fetch = async () => json({ detail: "Token has expired." }, { status: 401 });
  await assert.rejects(api.logoutEverywhere(), { status: 401 });
  assert.equal(fired, 0);
});
