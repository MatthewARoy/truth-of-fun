// Serve the `next build` output the way the container does: the standalone
// server, with the static assets copied next to it (the Dockerfile does the
// same copy). Used by playwright.prod.config.ts.
import { cpSync, existsSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

const webRoot = join(dirname(fileURLToPath(import.meta.url)), "..", "..");
const standalone = join(webRoot, ".next", "standalone", "apps", "web");
const server = join(standalone, "server.js");
if (!existsSync(server)) {
  console.error("No production build found. Run `npm run build --workspace @truth-of-fun/web` first.");
  process.exit(1);
}
cpSync(join(webRoot, ".next", "static"), join(standalone, ".next", "static"), { recursive: true });
if (existsSync(join(webRoot, "public"))) {
  cpSync(join(webRoot, "public"), join(standalone, "public"), { recursive: true });
}
process.chdir(standalone);
await import(pathToFileURL(server).href);
