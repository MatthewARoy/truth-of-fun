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

## Scripts

- `npm run web:dev` — start Next.js dev server
- `npm run web:build` — build production app
- `npm run web:lint` — run lint checks
- `npm run web:typecheck` — run TypeScript checks
- `npm run web:test:e2e` — run Playwright tests

The browser suite covers route rendering, mocked successful API interactions,
request races, authentication navigation, logout cleanup, and unavailable-API
recovery. Run it with the backend stopped; it is not a full-stack acceptance
test. Shared HTTP retry/deadline behavior is covered separately with
`npm test --workspace @truth-of-fun/api-client`.
