import { test, expect } from "@playwright/test";
import { randomUUID } from "node:crypto";
import { Client } from "@modelcontextprotocol/sdk/client/index.js";
import { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import { InMemoryTransport } from "@modelcontextprotocol/sdk/inMemory.js";
import { TruthOfFunApiClient } from "@truth-of-fun/api-client";
import { registerTools } from "../../packages/mcp-server/dist/tools.js";

const apiUrl = `http://127.0.0.1:${process.env.SHARING_E2E_API_PORT ?? 8168}`;

test("MCP read-only token works against the real API, cannot save or escalate, and revokes", async ({ request }) => {
  const registration = await request.post(`${apiUrl}/auth/register`, {
    data: { email: `mcp-${randomUUID()}@example.com`, password: "mcp-token-test-password" },
  });
  expect(registration.status()).toBe(201);
  const owner = { Authorization: `Bearer ${(await registration.json()).access_token}` };
  const mint = await request.post(`${apiUrl}/users/me/tokens`, {
    headers: owner, data: { name: "MCP read-only acceptance", scopes: ["events:read", "profile:read"] },
  });
  expect(mint.status()).toBe(201);
  const token = await mint.json();
  const api = new TruthOfFunApiClient(apiUrl);
  api.setToken(token.token);
  const server = new McpServer({ name: "real-token-acceptance", version: "0.0.0" });
  registerTools(server, api);
  const client = new Client({ name: "real-token-client", version: "0.0.0" });
  const [clientTransport, serverTransport] = InMemoryTransport.createLinkedPair();
  await server.connect(serverTransport);
  await client.connect(clientTransport);
  try {
    const search = await client.callTool({ name: "search_events", arguments: { query: "Sharing acceptance jazz" } });
    expect(search.isError).toBeFalsy();
    const events = JSON.parse(search.content[0].text).events;
    expect(events.length).toBeGreaterThan(0);
    const profile = await client.callTool({ name: "get_my_profile", arguments: {} });
    expect(profile.isError).toBeFalsy();
    expect(JSON.parse(profile.content[0].text).saved_event_ids).toEqual([]);
    const refused = await client.callTool({ name: "save_event", arguments: { event_id: events[0].id } });
    expect(refused.isError).toBe(true);
    expect(refused.content[0].text).toContain("403");
    const escalation = await request.post(`${apiUrl}/users/me/tokens`, {
      headers: { Authorization: `Bearer ${token.token}` }, data: { name: "escalation", scopes: ["signals:write"] },
    });
    expect(escalation.status()).toBe(401);
    const metadata = await request.get(`${apiUrl}/users/me/tokens`, { headers: owner });
    const rows = await metadata.json();
    expect(rows[0].request_count).toBe(3);
    expect(rows[0].last_used_at).toBeTruthy();
    expect(rows[0]).not.toHaveProperty("token");
    expect(rows[0]).not.toHaveProperty("token_hash");
    const revoked = await request.delete(`${apiUrl}/users/me/tokens/${token.id}`, { headers: owner });
    expect(revoked.status()).toBe(204);
    const after = await client.callTool({ name: "get_my_profile", arguments: {} });
    expect(after.isError).toBe(true);
    expect(after.content[0].text).toContain("401");
  } finally {
    await client.close();
    await server.close();
  }
});
