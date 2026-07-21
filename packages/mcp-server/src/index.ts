#!/usr/bin/env node
/**
 * Truth of Fun MCP server (stdio).
 *
 * Exposes event discovery, itinerary planning, and platform health to Claude
 * Desktop / Claude Code and any other MCP client. See README.md for setup.
 *
 * Everything goes through the HTTP API via `packages/api-client`, never
 * directly to Postgres — a stdio server runs on the user's machine next to the
 * client and can reach the API, not the database, and auth belongs in the API
 * anyway.
 *
 * IMPORTANT: stdout is the MCP protocol channel. Every diagnostic must go to
 * stderr, or it corrupts the stream and the client disconnects.
 */

import { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import { StdioServerTransport } from "@modelcontextprotocol/sdk/server/stdio.js";
import { TruthOfFunApiClient } from "@truth-of-fun/api-client";

import { loadConfig } from "./config.js";
import { registerTools } from "./tools.js";

const SERVER_NAME = "truth-of-fun";
const SERVER_VERSION = "0.1.0";

/** Diagnostics go to stderr — stdout carries the protocol. */
function log(message: string): void {
  process.stderr.write(`[${SERVER_NAME}] ${message}\n`);
}

async function main(): Promise<void> {
  const config = loadConfig();
  const client = new TruthOfFunApiClient(config.apiUrl);

  if (config.token) {
    client.setToken(config.token);
    log("Using TOF_TOKEN for authenticated tools.");
  } else if (config.email && config.password) {
    // Exchanging credentials once at startup keeps the password out of every
    // request. It still lives in the client config, which is why a scoped,
    // revocable token (TOF_TOKEN) is the better option — see README.md.
    try {
      const auth = await client.login({ email: config.email, password: config.password });
      client.setToken(auth.access_token);
      log(`Signed in as ${config.email}.`);
    } catch (error) {
      const message = error instanceof Error ? error.message : String(error);
      log(`Sign-in failed (${message}). Continuing with read-only tools.`);
    }
  } else {
    log("No credentials configured — only unauthenticated tools will work.");
  }

  const server = new McpServer({ name: SERVER_NAME, version: SERVER_VERSION });
  registerTools(server, client);

  const transport = new StdioServerTransport();
  await server.connect(transport);
  log(`Ready. API: ${config.apiUrl}`);
}

main().catch((error) => {
  const message = error instanceof Error ? error.stack || error.message : String(error);
  log(`Fatal: ${message}`);
  process.exit(1);
});
