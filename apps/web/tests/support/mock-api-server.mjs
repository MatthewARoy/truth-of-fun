// A tiny stand-in for the API, used ONLY by the Next.js server during e2e
// runs (API_INTERNAL_URL points here). Browser requests never reach it: specs
// intercept those with page.route. It exists so that server-rendered output
// (generateMetadata, JSON-LD, sitemap, notFound) can be tested for real.
import { createServer } from "node:http";
import {
  MISSING_EVENT_ID, SSR_EVENTS, SSR_FOLDER, SSR_FOLDER_TOKEN, SSR_PLAN, SSR_PLAN_TOKEN,
  UNREACHABLE_EVENT_ID_FROM,
} from "./fixtures.mjs";

const port = Number(process.env.WEB_E2E_API_PORT ?? 8791);

function send(res, status, body) {
  res.writeHead(status, { "Content-Type": "application/json" });
  res.end(JSON.stringify(body));
}

createServer((req, res) => {
  const url = new URL(req.url ?? "/", "http://mock.invalid");
  const path = url.pathname;
  if (req.method !== "GET") return send(res, 405, { detail: "Method not allowed" });
  if (path === "/health") return send(res, 200, { status: "ok" });
  if (path === "/events") {
    const offset = Number(url.searchParams.get("offset") ?? 0);
    return send(res, 200, offset === 0 ? SSR_EVENTS : []);
  }
  const eventMatch = /^\/events\/(\d+)$/.exec(path);
  if (eventMatch) {
    const id = Number(eventMatch[1]);
    if (id >= UNREACHABLE_EVENT_ID_FROM) return send(res, 503, { detail: "Mock API unavailable" });
    const event = SSR_EVENTS.find((entry) => entry.id === id);
    if (!event || id === MISSING_EVENT_ID) return send(res, 404, { detail: "Event not found." });
    return send(res, 200, event);
  }
  if (path === `/shared/itineraries/${SSR_PLAN_TOKEN}`) return send(res, 200, SSR_PLAN);
  if (path === `/shared/folders/${SSR_FOLDER_TOKEN}`) return send(res, 200, SSR_FOLDER);
  return send(res, 404, { detail: "Not found." });
}).listen(port, "127.0.0.1", () => {
  console.log(`mock API for server-side rendering on http://127.0.0.1:${port}`);
});
