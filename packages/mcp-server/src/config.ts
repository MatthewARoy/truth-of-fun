/** Environment configuration for the MCP server. */

export type ServerConfig = {
  apiUrl: string;
  /** A user JWT from POST /auth/login. Optional: read tools work without it. */
  token: string | null;
  /** Credentials to exchange for a JWT at startup, if no token was supplied. */
  email: string | null;
  password: string | null;
  /**
   * Operator token for the gated health endpoints. Without it
   * get_platform_status is refused, which the tool reports rather than
   * crashing — every other tool works unaffected.
   */
  opsToken: string | null;
};

export function loadConfig(env: NodeJS.ProcessEnv = process.env): ServerConfig {
  return {
    apiUrl: (env.TOF_API_URL || "http://127.0.0.1:8000").replace(/\/$/, ""),
    token: env.TOF_TOKEN?.trim() || null,
    email: env.TOF_EMAIL?.trim() || null,
    password: env.TOF_PASSWORD || null,
    opsToken: env.TOF_OPS_TOKEN?.trim() || null,
  };
}
