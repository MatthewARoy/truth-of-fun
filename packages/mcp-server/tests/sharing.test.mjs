import assert from "node:assert/strict";
import { afterEach, test } from "node:test";
import { Client } from "@modelcontextprotocol/sdk/client/index.js";
import { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import { InMemoryTransport } from "@modelcontextprotocol/sdk/inMemory.js";
import { TruthOfFunApiClient } from "@truth-of-fun/api-client";
import { registerTools } from "../dist/tools.js";

const originalFetch = globalThis.fetch;
afterEach(() => { globalThis.fetch = originalFetch; });
const token = "abcdefghijklmnopqrstuvwx";
const stops = [{ event_id: 42, kind: "main_event", travel_buffer_minutes_before: 0 }];
const share = { publish_publicly: true, stops };

async function setup(t, { authenticated = true, respond } = {}) {
  const requests = [];
  globalThis.fetch = async (url, init) => {
    requests.push({ url, ...init });
    return respond ? respond(url, init) : new Response(JSON.stringify({
      share_token: token, share_url: `/itinerary/${token}`, expires_at: "2026-10-13T00:00:00Z",
    }));
  };
  const api = new TruthOfFunApiClient("https://stub.invalid");
  if (authenticated) api.setToken("test-user-token");
  else api.setOpsToken("test-operator-token");
  const server = new McpServer({ name: "sharing-test", version: "0.0.0" });
  registerTools(server, api);
  const client = new Client({ name: "sharing-test-client", version: "0.0.0" });
  const [clientTransport, serverTransport] = InMemoryTransport.createLinkedPair();
  await server.connect(serverTransport);
  await client.connect(clientTransport);
  t.after(async () => { await client.close(); await server.close(); });
  return { client, requests };
}

test("public sharing advertises explicit consent, strict inputs, and mutation annotations", async (t) => {
  const { client } = await setup(t);
  const { tools } = await client.listTools();
  const publish = tools.find((tool) => tool.name === "share_itinerary");
  assert.ok(publish);
  assert.deepEqual(publish.annotations, {
    readOnlyHint: false, destructiveHint: false, idempotentHint: false, openWorldHint: true,
  });
  assert.ok(publish.inputSchema.required.includes("publish_publicly"));
  assert.equal(publish.inputSchema.properties.publish_publicly.const, true);
  assert.equal(publish.inputSchema.properties.publish_publicly.default, undefined);
  assert.equal(publish.inputSchema.additionalProperties, false);
  assert.equal(publish.inputSchema.properties.query, undefined);
  assert.match(publish.description, /explicit.*public/i);
  assert.match(publish.description, /planning.*saving.*copying/i);
  const revoke = tools.find((tool) => tool.name === "revoke_itinerary");
  assert.equal(revoke.annotations.readOnlyHint, false);
  assert.equal(revoke.annotations.idempotentHint, true);
  assert.equal(revoke.annotations.destructiveHint, true);
});

test("missing or false publication consent is rejected before an API request", async (t) => {
  const { client, requests } = await setup(t);
  for (const args of [{ stops }, { ...share, publish_publicly: false }]) {
    const result = await client.callTool({ name: "share_itinerary", arguments: args });
    assert.equal(result.isError, true);
    assert.match(result.content[0].text, /Input validation error/);
  }
  assert.equal(requests.length, 0);
});

test("share/list/revoke require user authentication before reaching the API", async (t) => {
  const { client, requests } = await setup(t, { authenticated: false });
  for (const [name, args] of [["share_itinerary", share], ["list_my_itineraries", {}], ["revoke_itinerary", { share_token: token }]]) {
    const result = await client.callTool({ name, arguments: args });
    assert.equal(result.isError, true);
    assert.match(result.content[0].text, /TOF_TOKEN/);
  }
  assert.equal(requests.length, 0, "an operator token is not a signed-in user");
});

test("private free-form fields cannot enter the public sharing payload", async (t) => {
  const { client, requests } = await setup(t);
  for (const args of [
    { ...share, query: "private planning context" },
    { ...share, intent: "private planning context" },
    { ...share, geography: "private home address" },
    { ...share, stops: [{ ...stops[0], title: "private notes" }] },
  ]) {
    const result = await client.callTool({ name: "share_itinerary", arguments: args });
    assert.equal(result.isError, true);
    assert.match(result.content[0].text, /Input validation error/);
  }
  assert.equal(requests.length, 0);
});

test("sharing forwards selected event identities with authentication and a 14-day default", async (t) => {
  const { client, requests } = await setup(t);
  const result = await client.callTool({ name: "share_itinerary", arguments: share });
  assert.notEqual(result.isError, true);
  assert.equal(requests.length, 1);
  assert.equal(requests[0].url, "https://stub.invalid/concierge/itinerary/share");
  assert.equal(requests[0].method, "POST");
  assert.equal(new Headers(requests[0].headers).get("Authorization"), "Bearer test-user-token");
  const body = JSON.parse(requests[0].body);
  assert.deepEqual(body.stops, stops);
  assert.equal(body.anchor_event_id, 42);
  assert.equal(body.expires_in_days, 14);
  assert.equal("query" in body, false);
  assert.equal("publish_publicly" in body, false);
  assert.equal(JSON.parse(result.content[0].text).share_token, token);
});

test("expiry is integral and bounded to 1 through 30 days", async (t) => {
  const { client, requests } = await setup(t);
  for (const expires_in_days of [0, 31, 1.5, "14"]) {
    const result = await client.callTool({ name: "share_itinerary", arguments: { ...share, expires_in_days } });
    assert.equal(result.isError, true);
  }
  assert.equal(requests.length, 0);
  for (const expires_in_days of [1, 30]) {
    const result = await client.callTool({ name: "share_itinerary", arguments: { ...share, expires_in_days } });
    assert.notEqual(result.isError, true);
  }
  assert.deepEqual(requests.map((r) => JSON.parse(r.body).expires_in_days), [1, 30]);
});

test("building a private suggestion never publishes or carries its query into later sharing", async (t) => {
  const { client, requests } = await setup(t, { respond: async (url) =>
    new Response(JSON.stringify(url.endsWith("/concierge/itinerary") ? { itinerary: [], title: "Plan" } : { share_token: token })) });
  const result = await client.callTool({ name: "build_itinerary", arguments: { query: "private planning context" } });
  assert.notEqual(result.isError, true);
  assert.deepEqual(requests.map((r) => r.url), ["https://stub.invalid/concierge/itinerary"]);
  await client.callTool({ name: "share_itinerary", arguments: share });
  assert.equal(JSON.stringify(JSON.parse(requests[1].body)).includes("private planning context"), false);
});

test("owner listing and revocation forward the authenticated API contract", async (t) => {
  const { client, requests } = await setup(t, { respond: async (_url, init) =>
    init.method === "DELETE" ? new Response(null, { status: 204 }) : new Response("[]") });
  const listed = await client.callTool({ name: "list_my_itineraries", arguments: { limit: 10, offset: 20 } });
  assert.notEqual(listed.isError, true);
  const revoked = await client.callTool({ name: "revoke_itinerary", arguments: { share_token: token } });
  assert.notEqual(revoked.isError, true);
  assert.equal(requests[0].url, "https://stub.invalid/users/me/itineraries?limit=10&offset=20");
  assert.equal(requests[1].url, `https://stub.invalid/users/me/itineraries/${token}`);
  assert.equal(requests[1].method, "DELETE");
  assert.ok(requests.every((r) => new Headers(r.headers).get("Authorization") === "Bearer test-user-token"));
});
