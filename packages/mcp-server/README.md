# Truth of Fun MCP server

Exposes Truth of Fun event discovery to Claude Desktop, Claude Code, and any
other MCP client, so you can ask *"what comedy is on this weekend?"* or
*"plan a date night in the Mission"* without leaving the conversation.

It talks to the HTTP API through `packages/api-client` — never directly to
Postgres. A stdio server runs on your machine next to the client and can reach
the API, not the database; and authentication belongs in the API, where every
caller is subject to the same rules.

## Setup

```bash
make install          # or: npm install && npm run mcp-server:build
```

Then point your MCP client at the built server.

**Claude Code:**

```bash
claude mcp add truth-of-fun \
  --env TOF_API_URL=http://127.0.0.1:8000 \
  -- node /absolute/path/to/truth-of-fun/packages/mcp-server/dist/index.js
```

**Claude Desktop** — in `claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "truth-of-fun": {
      "command": "node",
      "args": ["/absolute/path/to/truth-of-fun/packages/mcp-server/dist/index.js"],
      "env": { "TOF_API_URL": "http://127.0.0.1:8000" }
    }
  }
}
```

The API must be running (`make api`). Verify with `make status`.

## Configuration

| Variable | Required | Notes |
| --- | --- | --- |
| `TOF_API_URL` | no | Defaults to `http://127.0.0.1:8000` |
| `TOF_TOKEN` | no | A JWT from `POST /auth/login`. Enables the authenticated tools. |
| `TOF_EMAIL` / `TOF_PASSWORD` | no | Alternative to `TOF_TOKEN`: exchanged for a JWT once at startup. |

Without credentials the read tools still work — the events API is
unauthenticated. Personalization and anything that writes will return a clear
"not authorized" message.

### On credentials

The platform has no scoped, revocable API tokens yet, so the only credential is
a user JWT (7-day expiry) or the password that mints one. That means:

- `TOF_PASSWORD` puts your actual account password in a config file. Prefer
  `TOF_TOKEN`, which at least expires.
- A token today carries full user authority; it cannot be limited to read-only
  or revoked without changing your password.

Scoped Personal Access Tokens are Workstream A of
`docs/proposals/2026-07-agentic-platform.md`, and are the intended fix. Until
they exist, treat this server as something you run against your own account on
your own machine.

## Tools

| Tool | Auth | What it does |
| --- | --- | --- |
| `search_events` | no | Keyword / tag / time / geo search. Returns a page plus total match count. |
| `get_event` | no | One event with source provenance and first-seen time. |
| `build_itinerary` | no | Natural language → sequenced itinerary with travel buffers. Not saved. |
| `get_platform_status` | no | Is the platform healthy? Use it to qualify freshness claims. |
| `get_recommendations` | yes | Personalized ranking with per-event match scores. |
| `save_event` | yes | Save an event; also feeds the recommender. |
| `record_feedback` | yes | Record a like or a click. |
| `list_folders` / `create_folder` / `add_event_to_folder` | yes | Shortlist folders — the shareable output of a planning session. |

### Honesty rules the tools encode

These are in the tool descriptions themselves, because that is what the model
reads:

- **`first_seen_at` is not an announcement date.** It is when Truth of Fun
  ingested the event. The field is named for what it means so a model can't
  mistake it for when the event went public.
- **Cite the source.** Every event carries `external_url`, and tools instruct
  the model to include it — matching the project's responsible-scraping
  "link back" norm.
- **Itineraries are suggestions, not commitments.** `build_itinerary` returns a
  plan but nothing persists it, and the tool says so, so a model doesn't tell
  someone their evening is booked.
- **There is no dislike signal.** `record_feedback` documents that the platform
  has no negative-feedback channel, rather than letting a model imply one.

## Development

```bash
npm run mcp-server:build       # compile to dist/
npm run mcp-server:typecheck   # types only
```

Diagnostics go to **stderr** — stdout is the MCP protocol channel, and anything
written there corrupts the stream and disconnects the client.
