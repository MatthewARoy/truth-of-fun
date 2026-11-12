import { defineConfig } from "@playwright/test";
import base from "./playwright.config";

// Runs the same specs against the production build instead of `next dev`:
//
//   npm run build --workspace @truth-of-fun/web
//   npx playwright test --config playwright.prod.config.ts
//
// Worth doing before a release because production differs from development in
// ways the specs care about: the Content-Security-Policy has no 'unsafe-eval',
// error pages hide messages, and pages are prerendered.
const PORT = Number(process.env.WEB_E2E_PORT ?? process.env.PORT ?? 3000);
const API_PORT = Number(process.env.WEB_E2E_API_PORT ?? 8791);

export default defineConfig({
  ...base,
  // This spec drives navigation through `window.next.router`, a handle that
  // only exists in development builds.
  grepInvert: /navigating to an unavailable token never retains the previous shared plan/,
  webServer: [
    {
      command: "node tests/support/mock-api-server.mjs",
      url: `http://127.0.0.1:${API_PORT}/health`,
      reuseExistingServer: false,
      timeout: 30_000,
      env: { WEB_E2E_API_PORT: String(API_PORT) },
    },
    {
      command: "node tests/support/serve-production.mjs",
      url: `http://127.0.0.1:${PORT}/healthz`,
      reuseExistingServer: false,
      timeout: 60_000,
      env: {
        PORT: String(PORT),
        HOSTNAME: "127.0.0.1",
        API_INTERNAL_URL: `http://127.0.0.1:${API_PORT}`,
      },
    },
  ],
});
