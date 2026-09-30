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
