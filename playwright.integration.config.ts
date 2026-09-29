import { defineConfig } from "@playwright/test";

const webPort = Number(process.env.SHARING_E2E_WEB_PORT ?? 3177);
const apiPort = Number(process.env.SHARING_E2E_API_PORT ?? 8168);
const webUrl = `http://127.0.0.1:${webPort}`;
const apiUrl = `http://127.0.0.1:${apiPort}`;
const database = process.env.SHARING_E2E_DATABASE_URL;
if (!database) throw new Error("Set SHARING_E2E_DATABASE_URL to a disposable local database ending in _test.");

// Build first with NEXT_PUBLIC_API_BASE_URL matching apiUrl. These tests run the
// production browser bundle against the actual API, without intercepted requests.
export default defineConfig({
  testDir: "./tests/browser",
  outputDir: "./apps/web/test-results/integration",
  workers: 1,
  timeout: 60_000,
  use: { baseURL: webUrl, trace: "retain-on-failure" },
  webServer: [
    {
      command: ".venv/bin/python tests/browser/serve_api.py",
      url: `${apiUrl}/openapi.json`,
      reuseExistingServer: false,
      timeout: 60_000,
      env: {
        DATABASE_URL: database,
        SHARING_E2E_API_PORT: String(apiPort),
        APP_ENV: "development",
        AAIM_ENABLED: "false",
        ANTHROPIC_API_KEY: "",
        TICKETMASTER_API_KEY: "",
        ALERT_WEBHOOK_URL: "",
        CORS_ALLOWED_ORIGINS: JSON.stringify([webUrl]),
        PYTHONDONTWRITEBYTECODE: "1",
      },
    },
    {
      command: "node tests/browser/serve_web.mjs",
      url: webUrl,
      reuseExistingServer: false,
      timeout: 60_000,
      env: { NEXT_PUBLIC_API_BASE_URL: apiUrl, PORT: String(webPort), HOSTNAME: "127.0.0.1" },
    },
  ],
});
