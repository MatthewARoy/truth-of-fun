import { TruthOfFunApiClient } from "@truth-of-fun/api-client";

/**
 * Where the browser reaches the API. `NEXT_PUBLIC_API_BASE_URL` is inlined at
 * build time. Production serves the API from the same origin under `/api`, so
 * a relative value is valid here; local development talks to the API directly
 * on port 8000. Server-side rendering cannot use a relative URL — see
 * `lib/api/server.ts`.
 */
export const API_BASE_URL = process.env.NEXT_PUBLIC_API_BASE_URL || "http://127.0.0.1:8000";

export const apiClient = new TruthOfFunApiClient(API_BASE_URL);
