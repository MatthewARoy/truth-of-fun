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
| `TOF_TOKEN` | no | Scoped `tof_pat_...` token recommended; legacy user JWT also supported. |
| `TOF_EMAIL` / `TOF_PASSWORD` | no | Alternative to `TOF_TOKEN`: exchanged for a JWT once at startup. |
| `TOF_OPS_TOKEN` | no | Operator token for `get_platform_status`. Without it that one tool reports that the endpoint is gated; every other tool is unaffected. |

Without credentials the read tools still work — the events API is
unauthenticated. Personalization and anything that writes will return a clear
"not authorized" message.

### Connect with a scoped token

Sign in to the API as the account owner, then use `POST /users/me/tokens`
with your user JWT to mint a named token. For read-only MCP personalization:

```json
{ "name": "Claude read-only", "scopes": ["events:read", "profile:read"], "expires_in_days": 30 }
```

Copy the returned `tof_pat_<prefix>_<secret>` into `TOF_TOKEN`. The raw secret
is returned once; the API stores only its SHA-256 hash. `GET /users/me/tokens`
shows last use, request count, expiry and revocation. `DELETE
/users/me/tokens/{id}` revokes it. All three management routes require the
owner's user JWT; agent tokens cannot manage credentials or reach
`/internal/secrets/*`. This workflow never gives an agent your password.

Supported scopes:

| Scope | Tools / authority |
| --- | --- |
| `events:read` | search, event detail, corpus-only itinerary building |
| `profile:read` | get_my_profile; with events:read, personalized recommendations/planning |
| `signals:write` | save/feedback; also requires profile:read because the existing response contains profile state |
| `plans:read` | list your existing itinerary links |

Public publication/revocation, folder mutations, onboarding and explicit
preference replacement retain their user-JWT requirements. Legacy JWT and
startup login configurations remain compatible for those interactive actions;
prefer scoped tokens for agent use. Tokens do not grant operator access.
Agent requests are limited to 120 per minute per API replica, and existing
per-IP auth/LLM/share caps still apply. Revocation blocks subsequent admissions;
requests already admitted may finish. Anonymous public browsing remains public.

## Tools

| Tool | Auth | What it does |
| --- | --- | --- |
| `search_events` | no | Keyword / tag / time / geo search. Returns a page plus total match count. |
| `get_event` | no | One event with source provenance and first-seen time. |
| `build_itinerary` | no | Natural language → sequenced itinerary with travel buffers. Not saved. |
| `share_itinerary` | yes | Publish selected event stops after an explicit request for a public link; requires `publish_publicly: true`. |
| `list_my_itineraries` | yes | Inspect your published links, expiry dates, and revocation status. |
| `revoke_itinerary` | yes | Revoke one of your public links when requested. |
| `get_platform_status` | operator token | Is the platform healthy? Use it to qualify freshness claims. |
| `get_my_profile` | profile:read | Read preferences, saved IDs and learned weights. |
| `get_recommendations` | events:read + profile:read | Personalized ranking with per-event match scores. |
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
- **Itineraries are suggestions, not commitments.** `build_itinerary` does not
  save or publish its result, book tickets, or add a calendar entry.
- **Publishing requires an explicit request.** Planning, saving, or copying a
  plan does not authorize a public link. `share_itinerary` requires a literal
  `publish_publicly: true` with no default, and a configured user token. The
  tool rejects free-form query, title, and note fields; it sends selected event
  identities plus bounded metadata, and the API reads event details itself.
- **Public links have a lifetime and an owner.** Links expire after 14 days by
  default, with a maximum of 30 days. `list_my_itineraries` shows the owner's
  links; `revoke_itinerary` withdraws a link on request. These tools call the
  authenticated API, which enforces ownership. No original planning query is
  included in the public snapshot.
- **There is no dislike signal.** `record_feedback` documents that the platform
  has no negative-feedback channel, rather than letting a model imply one.

## Development

```bash
npm run mcp-server:build       # compile to dist/
npm run mcp-server:typecheck   # types only
npm test --workspace @truth-of-fun/mcp-server  # in-memory MCP protocol + mocked HTTP
```

The test command builds the API client and MCP server before testing. Tests
exercise registered tools through a real MCP client/server connection with an
in-memory transport; API requests are intercepted and nothing is published.

Diagnostics go to **stderr** — stdout is the MCP protocol channel, and anything
written there corrupts the stream and disconnects the client.
