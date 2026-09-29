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
