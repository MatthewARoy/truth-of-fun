// Serve the actual standalone output selected by next.config.ts. Next does not
// copy static/public assets into that output automatically (a CDN may own them).
import { cpSync, existsSync } from "node:fs";

const web = new URL("../../apps/web/", import.meta.url);
const standalone = new URL(".next/standalone/apps/web/", web);
if (!existsSync(new URL("server.js", standalone))) {
  throw new Error("Build the web app before running the sharing integration test.");
}
cpSync(new URL(".next/static/", web), new URL(".next/static/", standalone), { recursive: true });
if (existsSync(new URL("public/", web))) {
  cpSync(new URL("public/", web), new URL("public/", standalone), { recursive: true });
}
await import(new URL("server.js", standalone).href);
