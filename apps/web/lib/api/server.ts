import "server-only";
import { TruthOfFunApiClient } from "@truth-of-fun/api-client";

const DEV_DEFAULT = "http://127.0.0.1:8000";

function isAbsoluteHttpUrl(value: string | undefined): value is string {
  return Boolean(value && /^https?:\/\//i.test(value));
}

/**
 * Absolute API base URL for code that runs on the server (generateMetadata,
 * sitemap, server components). The browser's base URL may be relative
 * (`/api`), which means nothing to Node's fetch, so resolve in this order:
 *
 * 1. `API_INTERNAL_URL` — read at runtime; the address of the API on the
 *    private network (e.g. `http://api:8000`).
 * 2. `NEXT_PUBLIC_API_BASE_URL`, when it is absolute.
 * 3. The local development default.
 */
export function serverApiBaseUrl(): string {
  const internal = process.env.API_INTERNAL_URL?.trim();
  if (internal) return internal.replace(/\/+$/, "");
  const publicBase = process.env.NEXT_PUBLIC_API_BASE_URL?.trim();
  if (isAbsoluteHttpUrl(publicBase)) return publicBase.replace(/\/+$/, "");
  return DEV_DEFAULT;
}

/** An anonymous client for server-side reads of public endpoints. */
export function serverApiClient(): TruthOfFunApiClient {
  return new TruthOfFunApiClient(serverApiBaseUrl());
}

/**
 * Server-side reads sit in front of a page render, so they get a short
 * deadline and no retry: a slow API must degrade the page, not hang it.
 */
export const SERVER_REQUEST = { retries: 0, timeoutMs: 4_000 } as const;
