import type { MetadataRoute } from "next";
import { serverApiClient } from "@/lib/api/server";
import { SITE_URL } from "@/lib/site";

// Rendered per request (the event list comes from the API, which is not
// reachable at build time) and memoised in-process so crawlers cannot turn
// this route into API load.
export const dynamic = "force-dynamic";

const STATIC_ROUTES: Array<{ path: string; changeFrequency: "hourly" | "weekly" | "monthly"; priority: number }> = [
  { path: "/", changeFrequency: "weekly", priority: 1 },
  { path: "/explore", changeFrequency: "hourly", priority: 0.9 },
  { path: "/planner", changeFrequency: "monthly", priority: 0.6 },
  { path: "/privacy", changeFrequency: "monthly", priority: 0.2 },
  { path: "/terms", changeFrequency: "monthly", priority: 0.2 },
];

const PAGE_SIZE = 200; // the API's maximum
const MAX_EVENTS = 2_000;
const FRESH_MS = 15 * 60_000;
// After a failure, serve static routes and wait a little before asking again.
const RETRY_MS = 60_000;

let memo: { expires: number; events: MetadataRoute.Sitemap } | null = null;

async function upcomingEventEntries(): Promise<MetadataRoute.Sitemap> {
  if (memo && memo.expires > Date.now()) return memo.events;
  const api = serverApiClient();
  const events: MetadataRoute.Sitemap = [];
  let expires = Date.now() + FRESH_MS;
  try {
    for (let offset = 0; offset < MAX_EVENTS; offset += PAGE_SIZE) {
      // GET /events lists upcoming events by default.
      const page = await api.getEvents({ limit: PAGE_SIZE, offset }, { retries: 0, timeoutMs: 5_000 });
      for (const event of page) {
        if (!Number.isInteger(event.id) || event.status === "cancelled") continue;
        events.push({
          url: `${SITE_URL}/events/${event.id}`,
          changeFrequency: "daily",
          priority: 0.7,
        });
      }
      if (page.length < PAGE_SIZE) break;
    }
  } catch {
    // Fail soft: whatever was collected so far (possibly nothing) is still a
    // valid sitemap alongside the static routes.
    expires = Date.now() + RETRY_MS;
  }
  memo = { expires, events };
  return events;
}

export default async function sitemap(): Promise<MetadataRoute.Sitemap> {
  const staticEntries: MetadataRoute.Sitemap = STATIC_ROUTES.map((route) => ({
    url: `${SITE_URL}${route.path === "/" ? "" : route.path}`,
    changeFrequency: route.changeFrequency,
    priority: route.priority,
  }));
  return [...staticEntries, ...(await upcomingEventEntries())];
}
