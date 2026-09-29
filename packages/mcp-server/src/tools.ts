/**
 * Tool registrations for the Truth of Fun MCP server.
 *
 * Every tool is a thin wrapper over `packages/api-client`, which is a thin
 * wrapper over the HTTP API. That layering is deliberate: authentication and
 * any future scoping live in FastAPI dependencies, so a tool that reached into
 * the service layer directly would bypass them and fork the contract. The
 * OpenAPI schema stays the single source of truth.
 *
 * Two honesty rules are encoded in the tool descriptions themselves, because
 * the description is what the model actually reads:
 *
 * 1. `first_seen_at` is when this platform ingested an event, never when the
 *    event was announced. Presenting it as an announcement date would be a
 *    fabricated fact.
 * 2. Every event carries `external_url`, and tools instruct the model to cite
 *    it — consistent with the project's responsible-scraping "link back" norm.
 */

import type {
  ApiClientError,
  EventsQuery,
  TruthOfFunApiClient,
} from "@truth-of-fun/api-client";
import type { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import { z } from "zod";

type ToolResult = {
  content: Array<{ type: "text"; text: string }>;
  isError?: boolean;
};

function ok(payload: unknown): ToolResult {
  return { content: [{ type: "text", text: JSON.stringify(payload, null, 2) }] };
}

function fail(message: string): ToolResult {
  return { content: [{ type: "text", text: message }], isError: true };
}

/**
 * Convert a thrown error into a tool error the model can act on.
 *
 * MCP tool handlers should report failures as results rather than throwing:
 * a thrown error is a protocol-level fault the model cannot see or recover
 * from, whereas an error result lets it retry or explain.
 */
function describeError(error: unknown, operatorTool = false): string {
  const apiError = error as Partial<ApiClientError> & { status?: number };
  if (typeof apiError?.status === "number") {
    if (apiError.status === 401 || apiError.status === 403) {
      if (operatorTool) return `Operator authorization required (HTTP ${apiError.status}). Configure TOF_OPS_TOKEN for get_platform_status; a user token does not grant operator access.`;
      return (
        `Not authorized (HTTP ${apiError.status}). This tool needs a signed-in ` +
        "user. Set TOF_TOKEN (or TOF_EMAIL/TOF_PASSWORD) in the MCP server " +
        "configuration and restart the client."
      );
    }
    if (apiError.status === 404) {
      return `Not found (HTTP 404): ${apiError.message ?? "no such resource"}`;
    }
    return `API error (HTTP ${apiError.status}): ${apiError.message ?? "request failed"}`;
  }
  const message = error instanceof Error ? error.message : String(error);
  return (
    `Could not reach the Truth of Fun API: ${message}. ` +
    "Check TOF_API_URL and that the API is running."
  );
}

async function guard(run: () => Promise<ToolResult>, operatorTool = false): Promise<ToolResult> {
  try {
    return await run();
  } catch (error) {
    return fail(describeError(error, operatorTool));
  }
}

const CITATION_NOTE =
  "Every event includes external_url — cite it when relaying an event to a person.";

const FIRST_SEEN_NOTE =
  "first_seen_at is when Truth of Fun first ingested this event, NOT when the " +
  "event was announced. Do not describe it as an announcement or on-sale date.";

const PUBLIC_SHARE_INPUT = z.strictObject({
  publish_publicly: z.literal(true).describe(
    "Required explicit confirmation: the user asked to publish these selected stops as a public link."
  ),
  stops: z.array(z.strictObject({
    event_id: z.number().int().positive(),
    kind: z.enum(["before_event", "main_event", "after_event", "pre_event_drink", "late_night_snack"]),
    travel_buffer_minutes_before: z.number().int().min(0).max(1440).default(0),
  })).min(1).max(20).describe("The selected event identities in itinerary order; no titles, prompts or notes."),
  intent: z.enum(["date_night", "out_of_town_guests", "bar_crawl", "active_day", "general_night_out"])
    .default("general_night_out"),
  timeframe: z.enum([
    "tonight", "tomorrow", "this_weekend", "upcoming_week", "this_monday", "this_tuesday",
    "this_wednesday", "this_thursday", "this_friday", "this_saturday", "this_sunday",
  ]).default("upcoming_week"),
  geography: z.enum([
    "financial district", "north beach", "russian hill", "nob hill", "potrero hill",
    "south bay", "san francisco", "san jose", "oakland", "berkeley", "mission", "castro",
    "marina", "richmond", "sunset", "dogpatch", "tenderloin", "downtown", "fidi", "soma", "noe", "sf",
  ]).nullable().optional(),
  expires_in_days: z.number().int().min(1).max(30).default(14)
    .describe("Public-link lifetime in days; defaults to 14 and cannot exceed 30."),
});

function authenticationRequired(client: TruthOfFunApiClient): ToolResult | undefined {
  if (!client.getToken()?.trim()) {
    return fail(
      "This tool requires a signed-in user. Configure TOF_TOKEN (or TOF_EMAIL/TOF_PASSWORD) " +
      "before publishing, listing, or revoking itinerary links. An operator token does not grant user access."
    );
  }
}

export function registerTools(server: McpServer, client: TruthOfFunApiClient): void {
  server.registerTool(
    "search_events",
    {
      title: "Search events",
      description:
        "Search upcoming events by keyword, vibe tag, time window, location, " +
        "or distance from a point. Returns a page of events plus the total " +
        "number of matches, so you can tell whether to page further. " +
        CITATION_NOTE,
      inputSchema: {
        query: z
          .string()
          .optional()
          .describe("Full-text search over title and description"),
        vibe_tag: z
          .string()
          .optional()
          .describe("Filter to events carrying this exact vibe tag, e.g. '#Jazz'"),
        time_preset: z
          .enum(["tonight", "this_weekend"])
          .optional()
          .describe("Convenience time window, resolved in San Francisco local time"),
        location_preset: z.enum(["sf", "oakland", "san_jose"]).optional(),
        start_at: z
          .string()
          .optional()
          .describe("ISO 8601 lower bound on event start time"),
        end_at: z.string().optional().describe("ISO 8601 upper bound on event start time"),
        lat: z.number().optional().describe("Latitude; requires lng and radius_miles"),
        lng: z.number().optional().describe("Longitude; requires lat and radius_miles"),
        radius_miles: z
          .number()
          .positive()
          .optional()
          .describe("Search radius; requires lat and lng"),
        sort_by: z
          .enum(["date", "distance"])
          .optional()
          .describe("'distance' requires lat/lng/radius_miles"),
        limit: z.number().int().min(1).max(200).optional().describe("Default 25"),
        offset: z.number().int().min(0).optional(),
      },
      annotations: { readOnlyHint: true, idempotentHint: true, openWorldHint: true },
    },
    async (args) =>
      guard(async () => {
        const { query, ...rest } = args as Record<string, unknown>;
        const eventsQuery = { ...rest, q: query } as EventsQuery;
        const page = await client.getEventsPage(eventsQuery);
        return ok({
          total_matches: page.total,
          returned: page.events.length,
          events: page.events,
          note: page.events.length === 0 ? "No events matched these filters." : undefined,
        });
      })
  );

  server.registerTool(
    "get_event",
    {
      title: "Get event detail",
      description:
        "Fetch one event by id, including which source it came from " +
        "(source_name, source_tier) and when this platform first saw it. " +
        FIRST_SEEN_NOTE,
      inputSchema: { event_id: z.number().int().describe("Event id from search_events") },
      annotations: { readOnlyHint: true, idempotentHint: true, openWorldHint: true },
    },
    async ({ event_id }) =>
      guard(async () => ok(await client.getEvent(event_id)))
  );

  server.registerTool(
    "get_recommendations",
    {
      title: "Get personalized recommendations",
      description:
        "Ranked recommendations for the signed-in user, blending vibe match, " +
        "popularity, freshness, and category diversity. match_score and " +
        "matched_vibes explain why each event was chosen. Requires " +
        "authentication. " +
        CITATION_NOTE,
      inputSchema: {
        limit: z.number().int().min(1).max(100).optional().describe("Default 25"),
        offset: z.number().int().min(0).optional(),
      },
      annotations: { readOnlyHint: true, idempotentHint: true, openWorldHint: true },
    },
    async ({ limit, offset }) =>
      guard(async () => ok(await client.getRecommendations(limit ?? 25, offset ?? 0)))
  );

  server.registerTool(
    "build_itinerary",
    {
      title: "Build an itinerary from a natural-language request",
      description:
        "Turn a request like 'date night in the Mission on Saturday' into a " +
        "sequenced itinerary: an anchor event plus nearby pre- and post- " +
        "stops within half a mile, with travel buffers between them. " +
        "The result is returned without saving. The web planner supports " +
        "saved share links, but this tool only builds a suggestion. It does " +
        "not book anything or add it to a calendar. " +
        CITATION_NOTE,
      inputSchema: {
        query: z.string().describe("Natural-language request, in the user's own words"),
        limit: z
          .number()
          .int()
          .min(1)
          .max(100)
          .optional()
          .describe("Candidate pool size to sequence from (default 25)"),
      },
      // Not read-only in cost terms (it may make one LLM call server-side) but
      // it writes nothing, and repeating it is safe.
      annotations: { readOnlyHint: true, idempotentHint: false, openWorldHint: true },
    },
    async ({ query, limit }) =>
      guard(async () => {
        const itinerary = await client.buildItinerary({ query, limit: limit ?? 25 });
        return ok({
          ...itinerary,
          note:
            itinerary.itinerary.length === 0
              ? "No events matched this request closely enough to sequence."
              : "This itinerary was not saved — it is a suggestion only.",
        });
      })
  );

  server.registerTool(
    "share_itinerary",
    {
      title: "Publish selected itinerary stops as a public link",
      description:
        "Publish a snapshot of selected event stops as a public link. Use only after the user " +
        "explicitly requests a public link for those stops. Planning, saving, or copying a plan " +
        "does not authorize publishing it. Requires publish_publicly=true and user authentication. " +
        "Anyone with the link can read the selected event details until it expires or the owner revokes it. " +
        "Do not include the original planning query or private context; this tool accepts only selected " +
        "event identities and bounded metadata. Default expiry is 14 days, maximum 30. " +
        "Use list_my_itineraries to inspect links and revoke_itinerary to withdraw a link on request.",
      inputSchema: PUBLIC_SHARE_INPUT,
      annotations: {
        readOnlyHint: false, destructiveHint: false, idempotentHint: false, openWorldHint: true,
      },
    },
    async ({ publish_publicly: _confirmation, stops, intent, timeframe, geography, expires_in_days }) =>
      guard(async () => {
        const unauthorized = authenticationRequired(client);
        if (unauthorized) return unauthorized;
        return ok(await client.shareItinerary({
          stops, intent, timeframe, geography,
          anchor_event_id: stops.find((stop) => stop.kind === "main_event")?.event_id ?? null,
          expires_in_days,
        }));
      })
  );

  server.registerTool(
    "list_my_itineraries",
    {
      title: "List my published itinerary links",
      description:
        "Inspect the signed-in user's published itinerary links, including expiry and revocation status. " +
        "Requires user authentication. Listing does not publish a new link or change an existing one.",
      inputSchema: z.strictObject({
        limit: z.number().int().min(1).max(100).default(25),
        offset: z.number().int().min(0).default(0),
      }),
      annotations: { readOnlyHint: true, idempotentHint: true, openWorldHint: true },
    },
    async ({ limit, offset }) => guard(async () => {
      const unauthorized = authenticationRequired(client);
      if (unauthorized) return unauthorized;
      return ok(await client.getMyItineraries(limit, offset));
    })
  );

  server.registerTool(
    "revoke_itinerary",
    {
      title: "Revoke my public itinerary link",
      description:
        "Revoke a public itinerary link owned by the signed-in user so the link no longer opens. " +
        "Use only when the user explicitly asks to revoke that link. Obtain its share_token from " +
        "list_my_itineraries or share_itinerary. Requires user authentication; the API checks ownership. " +
        "Repeating a successful revocation is safe.",
      inputSchema: z.strictObject({
        share_token: z.string().min(20).max(128).regex(/^[A-Za-z0-9_-]+$/),
      }),
      annotations: {
        readOnlyHint: false, destructiveHint: true, idempotentHint: true, openWorldHint: true,
      },
    },
    async ({ share_token }) => guard(async () => {
      const unauthorized = authenticationRequired(client);
      if (unauthorized) return unauthorized;
      await client.revokeItinerary(share_token);
      return ok({ share_token, status: "revoked" });
    })
  );

  server.registerTool(
    "get_platform_status",
    {
      title: "Get platform status",
      description:
        "Report whether the platform and its ingestion sources are healthy. " +
        "Use this to qualify freshness claims: if a source is failing or the " +
        "worker is stalled, say so rather than implying the feed is complete.",
      inputSchema: {},
      annotations: { readOnlyHint: true, idempotentHint: true, openWorldHint: true },
    },
    async () => guard(async () => ok(await client.getHealthSummary()), true)
  );

  server.registerTool(
    "save_event",
    {
      title: "Save an event for the user",
      description:
        "Save an event to the signed-in user's list. This also feeds the " +
        "recommender, so only save things the user actually asked for. " +
        "Requires authentication.",
      inputSchema: { event_id: z.number().int() },
      annotations: { readOnlyHint: false, idempotentHint: true, destructiveHint: false },
    },
    async ({ event_id }) =>
      guard(async () =>
        ok(await client.updateInterests({ action: "save", event_id }))
      )
  );

  server.registerTool(
    "record_feedback",
    {
      title: "Record a taste signal",
      description:
        "Record that the user liked a vibe tag, or clicked/opened an event. " +
        "These signals train the recommender and decay over 30 days. " +
        "Requires authentication. Note the platform currently has no negative " +
        "signal — there is no way to record a dislike, so do not claim one.",
      inputSchema: {
        action: z
          .enum(["like", "click", "external_ticket_click"])
          .describe("'like' takes a vibe_tag; the click actions take an event_id"),
        event_id: z.number().int().optional(),
        vibe_tag: z.string().optional().describe("e.g. '#LiveMusic'"),
      },
      annotations: { readOnlyHint: false, idempotentHint: false, destructiveHint: false },
    },
    async ({ action, event_id, vibe_tag }) =>
      guard(async () => {
        if (action === "like" && !vibe_tag) {
          return fail("record_feedback with action='like' requires vibe_tag.");
        }
        if (action !== "like" && event_id === undefined) {
          return fail(`record_feedback with action='${action}' requires event_id.`);
        }
        return ok(await client.updateInterests({ action, event_id, vibe_tag }));
      })
  );

  server.registerTool(
    "list_folders",
    {
      title: "List shortlist folders",
      description:
        "List the signed-in user's shortlist folders. Folders are the " +
        "event shortlists on this platform: each has a share_token that " +
        "produces a public link. Requires authentication.",
      inputSchema: {},
      annotations: { readOnlyHint: true, idempotentHint: true, openWorldHint: true },
    },
    async () => guard(async () => ok(await client.listFolders()))
  );

  server.registerTool(
    "create_folder",
    {
      title: "Create a shortlist folder",
      description:
        "Create a named folder to collect events into — the durable, " +
        "shareable output of a planning session. Returns a share_token. " +
        "Requires authentication.",
      inputSchema: { name: z.string().min(1).describe("e.g. 'Saturday date night'") },
      annotations: { readOnlyHint: false, idempotentHint: false, destructiveHint: false },
    },
    async ({ name }) => guard(async () => ok(await client.createFolder(name)))
  );

  server.registerTool(
    "add_event_to_folder",
    {
      title: "Add an event to a folder",
      description:
        "Add an event to one of the user's folders. Use this to persist an " +
        "itinerary built with build_itinerary, which is otherwise not saved. " +
        "Requires authentication.",
      inputSchema: {
        folder_id: z.number().int(),
        event_id: z.number().int(),
      },
      annotations: { readOnlyHint: false, idempotentHint: true, destructiveHint: false },
    },
    async ({ folder_id, event_id }) =>
      guard(async () => ok(await client.addFolderItem(folder_id, event_id)))
  );
}
