import { defineConfig } from "@playwright/test";

// Port is overridable (WEB_E2E_PORT / PORT) so the suite still runs when another
// process already owns 3000 — otherwise `reuseExistingServer` would silently
// drive the tests against the wrong server. Defaults to 3000.
const PORT = Number(process.env.WEB_E2E_PORT ?? process.env.PORT ?? 3000);

export default defineConfig({
  testDir: "./tests/e2e",
  timeout: 60_000,
  use: {
    baseURL: `http://127.0.0.1:${PORT}`,
    trace: "on-first-retry",
  },
  webServer: {
    command: `npm run dev -- --port ${PORT}`,
    port: PORT,
    reuseExistingServer: true,
    timeout: 120_000,
  },
});
