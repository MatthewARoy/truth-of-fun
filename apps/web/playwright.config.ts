import { defineConfig } from "@playwright/test";

// Port is overridable (WEB_E2E_PORT / PORT) so the suite still runs when another
// process already owns 3000. Tests start their own loopback server and never
// reuse a potentially stale checkout's server. Defaults to 3000.
const PORT = Number(process.env.WEB_E2E_PORT ?? process.env.PORT ?? 3000);

// Server-rendered output (share metadata, JSON-LD, sitemap, 404s) needs the
// Next.js *server* to reach an API. A tiny fixture server plays that part via
// API_INTERNAL_URL. The browser's API base is unchanged, so specs keep
// intercepting browser requests with page.route and run without a backend.
const API_PORT = Number(process.env.WEB_E2E_API_PORT ?? 8791);

// Optional: run against an already-installed Chromium instead of the browser
// revision this Playwright version downloads (useful on machines where
// `playwright install` is not allowed). Unset, Playwright's default applies.
const CHROMIUM_EXECUTABLE = process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH;

export default defineConfig({
  testDir: "./tests/e2e",
  timeout: 60_000,
  use: {
    baseURL: `http://127.0.0.1:${PORT}`,
    trace: "on-first-retry",
    ...(CHROMIUM_EXECUTABLE ? { launchOptions: { executablePath: CHROMIUM_EXECUTABLE } } : {}),
  },
  webServer: [
    {
      command: "node tests/support/mock-api-server.mjs",
      url: `http://127.0.0.1:${API_PORT}/health`,
      reuseExistingServer: false,
      timeout: 30_000,
      env: { WEB_E2E_API_PORT: String(API_PORT) },
    },
    {
      command: `npm run dev -- --hostname 127.0.0.1 --port ${PORT}`,
      port: PORT,
      reuseExistingServer: false,
      timeout: 120_000,
      env: { API_INTERNAL_URL: `http://127.0.0.1:${API_PORT}` },
    },
  ],
});
