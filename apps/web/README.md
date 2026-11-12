# Truth of Fun — Web

Next.js (App Router) frontend for the Truth of Fun event aggregator.

## Local setup

1. Install dependencies from the repo root:

   ```bash
   npm install
   ```

2. Copy the env template and set the API base URL:

   ```bash
   cp apps/web/.env.local.example apps/web/.env.local
   ```

3. Start the backend API (FastAPI) on `http://127.0.0.1:8000`.

4. Start the web app:

   ```bash
   npm run web:dev
   ```

## Configuration

| Variable | When it is read | Purpose |
| --- | --- | --- |
| `NEXT_PUBLIC_API_BASE_URL` | build | Where the browser reaches the API. Absolute (`http://127.0.0.1:8000`, the default) or same-origin relative (`/api`, what the production image uses). It also decides the `connect-src` of the Content-Security-Policy. |
| `NEXT_PUBLIC_SITE_URL` | build | Public origin, e.g. `https://example.com`. Used for canonical links, Open Graph URLs, `robots.txt` and `sitemap.xml`. **Set it for production builds**; the fallback is `http://localhost:3000`. |
| `API_INTERNAL_URL` | runtime (server) | Where the Next.js server reaches the API for server-rendered pages (`/events/[id]`, share-page metadata, sitemap). Required when `NEXT_PUBLIC_API_BASE_URL` is relative. Falls back to an absolute `NEXT_PUBLIC_API_BASE_URL`, then `http://127.0.0.1:8000`. |

If the server cannot reach the API, pages still work: event pages load their
data in the browser instead, and share pages and the sitemap fall back to
generic metadata and the static routes.

`GET /healthz` returns `200 ok` for container health checks.

## Scripts

- `npm run web:dev` — start Next.js dev server
- `npm run web:build` — build production app
- `npm run web:lint` — run lint checks
- `npm run web:typecheck` — run TypeScript checks
- `npm run web:test` / `npm run web:test:e2e` — run Playwright tests against `next dev`
- `npx playwright test --config playwright.prod.config.ts` (from `apps/web`, after
  `npm run web:build`) — run the same specs against the production build. Do
  this before a release: the production Content-Security-Policy is stricter
  than the development one (no `'unsafe-eval'`).

The browser suite covers route rendering, mocked successful API interactions,
request races, authentication navigation, logout cleanup, unavailable-API
recovery, Explore's URL state and filters, the event page and its metadata,
account flows, error/not-found pages, security headers and a
no-CSP-violations check. Run it with the backend stopped; it is not a
full-stack acceptance test. Browser requests to the API are intercepted per
spec with `page.route`. Server-rendered output is tested against a small
fixture API (`tests/support/mock-api-server.mjs`, port 8791, override with
`WEB_E2E_API_PORT`) that only the Next.js server talks to. Shared HTTP
retry/deadline behavior is covered separately with
`npm test --workspace @truth-of-fun/api-client`.

To use an already-installed Chromium instead of the revision Playwright would
download, set `PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH` to its executable.
