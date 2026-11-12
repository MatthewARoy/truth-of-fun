import type {
  AgentToken, MintAgentTokenRequest, MintAgentTokenResponse, MyProfile,
  AuthRequest,
  AuthResponse,
  ChangePasswordRequest,
  DeleteAccountRequest,
  DetailResponse,
  PasswordResetConfirmRequest,
  RegionsResponse,
  ConciergeRequest,
  ConciergeResponse,
  EventDetailResponse,
  EventResponse,
  EventsPage,
  EventsQuery,
  HealthSummary,
  FolderDetailResponse,
  FolderResponse,
  InterestRequest,
  InterestResponse,
  InviteResponse,
  OnboardingRequest,
  OnboardingResponse,
  PortableItineraryResponse,
  PreferencesRequest,
  RecommendationResponse,
  ShareItineraryRequest,
  SharedItinerarySummary,
  SourceHealthEntry,
} from "./types.js";

export class ApiClientError extends Error {
  status: number;
  payload: unknown;

  constructor(message: string, status: number, payload: unknown) {
    super(message);
    this.name = "ApiClientError";
    this.status = status;
    this.payload = payload;
  }
}

export type RequestOptions = {
  retries?: number;
  signal?: AbortSignal;
  /** Deadline for the entire operation, including retries. Defaults to 30s. */
  timeoutMs?: number;
};

/** Called when the API rejects the stored credential (HTTP 401). */
export type UnauthorizedHandler = (error: ApiClientError) => void;

export type ApiClientOptions = {
  /** See {@link TruthOfFunApiClient.setUnauthorizedHandler}. */
  onUnauthorized?: UnauthorizedHandler;
};

/** How a request relates to the stored user credential. */
type AuthMode =
  /** Send the token if there is one; a 401 means the session is no longer valid. */
  | "session"
  /** Never send the token (sign-in, sign-up, password reset): a 401 here is
   * a wrong password, not an expired session. */
  | "anonymous"
  /** Send the token, but a 401 is the caller's to handle (logging out with an
   * already-expired token is still a successful logout). */
  | "silent";

type InternalInit = RequestInit & { auth?: AuthMode };

/** Encode one path segment so an id or token can never alter the route. */
function seg(value: string | number): string {
  return encodeURIComponent(String(value));
}

const LOCATION_PREFIXES = new Set(["body", "query", "path", "header", "cookie"]);

/**
 * Turn an error payload into one readable sentence.
 *
 * FastAPI reports its own errors as `{detail: "..."}`, but request validation
 * (422) as `{detail: [{loc: ["body", "password"], msg: "...", type: "..."}]}`.
 * Without flattening, every validation failure reads "Request failed: 422".
 */
export function describeErrorPayload(payload: unknown, status: number): string {
  const fallback = `Request failed: ${status}`;
  if (typeof payload !== "object" || payload === null || !("detail" in payload)) return fallback;
  const detail = (payload as { detail?: unknown }).detail;
  if (typeof detail === "string") return detail.trim() || fallback;
  if (!Array.isArray(detail)) return fallback;
  const messages: string[] = [];
  for (const item of detail) {
    if (typeof item === "string") {
      if (item.trim()) messages.push(item.trim());
      continue;
    }
    if (typeof item !== "object" || item === null) continue;
    const { loc, msg } = item as { loc?: unknown; msg?: unknown };
    if (typeof msg !== "string" || !msg.trim()) continue;
    const field = Array.isArray(loc)
      ? loc
        .filter((part, index) => !(index === 0 && LOCATION_PREFIXES.has(String(part))))
        .map(String)
        .join(".")
      : "";
    // Pydantic prefixes custom validator messages with "Value error, ".
    const text = msg.trim().replace(/^Value error,\s*/i, "");
    const message = field ? `${field}: ${text}` : text;
    if (!messages.includes(message)) messages.push(message);
  }
  return messages.length > 0 ? messages.join("; ") : fallback;
}

const TRANSIENT_STATUSES = new Set([408, 429, 500, 502, 503, 504]);

function waitForRetry(delayMs: number, signal: AbortSignal): Promise<void> {
  return new Promise((resolve, reject) => {
    if (signal.aborted) return reject(signal.reason);
    const abort = () => {
      clearTimeout(timer);
      reject(signal.reason);
    };
    const timer = setTimeout(() => {
      signal.removeEventListener("abort", abort);
      resolve();
    }, delayMs);
    signal.addEventListener("abort", abort, { once: true });
  });
}

export class TruthOfFunApiClient {
  private readonly baseUrl: string;
  private token: string | null = null;
  private opsToken: string | null = null;
  private onUnauthorized: UnauthorizedHandler | null = null;

  /**
   * `baseUrl` may be absolute (`https://api.example.com`) or, in a browser,
   * relative to the page origin (`/api`).
   */
  constructor(baseUrl: string, options: ApiClientOptions = {}) {
    this.baseUrl = baseUrl.replace(/\/+$/, "");
    this.onUnauthorized = options.onUnauthorized ?? null;
  }

  getBaseUrl(): string {
    return this.baseUrl;
  }

  /**
   * Register a callback for an expired or revoked session: it fires when a
   * request that carried the stored token comes back 401, as long as that
   * token is still the stored one. Failed sign-in attempts never fire it.
   * The request still rejects with the ApiClientError.
   */
  setUnauthorizedHandler(handler: UnauthorizedHandler | null) {
    this.onUnauthorized = handler;
  }

  getMyProfile(options: RequestOptions = {}): Promise<MyProfile> {
    return this.request<MyProfile>("/users/me", {}, options);
  }

  /** Management endpoints require a user JWT; a PAT can never manage credentials. */
  mintAgentToken(payload: MintAgentTokenRequest): Promise<MintAgentTokenResponse> {
    return this.request<MintAgentTokenResponse>("/users/me/tokens", { method: "POST", body: JSON.stringify(payload) });
  }

  listAgentTokens(options: RequestOptions = {}): Promise<AgentToken[]> {
    return this.request<AgentToken[]>("/users/me/tokens", {}, options);
  }

  revokeAgentToken(id: number): Promise<void> {
    return this.request<void>(`/users/me/tokens/${seg(id)}`, { method: "DELETE" });
  }

  setToken(token: string | null) {
    this.token = token;
  }

  getToken(): string | null {
    return this.token;
  }

  /**
   * Operator token for the gated health endpoints (/health/sources,
   * /health/summary). Sent as X-Ops-Token, deliberately not Authorization:
   * that carries the signed-in user's JWT, and an operator is usually both.
   */
  setOpsToken(token: string | null) {
    this.opsToken = token;
  }

  getOpsToken(): string | null {
    return this.opsToken;
  }

  private async request<T>(
    path: string,
    init?: InternalInit,
    options?: RequestOptions
  ): Promise<T> {
    const { data } = await this.requestWithResponse<T>(path, init, options);
    return data;
  }

  /**
   * Same as request(), but also hands back the Response so callers can read
   * headers (X-Total-Count for pagination, X-Request-ID when reporting a bug).
   */
  private async requestWithResponse<T>(
    path: string,
    internalInit?: InternalInit,
    options?: RequestOptions
  ): Promise<{ data: T; response: Response }> {
    const { auth = "session", ...init } = internalInit ?? {};
    const url = `${this.baseUrl}${path}`;
    const method = (init.method || "GET").toUpperCase();
    const retryLimit = options?.retries ?? 1;
    const retries = method === "GET" && Number.isFinite(retryLimit)
      ? Math.min(3, Math.max(0, Math.floor(retryLimit))) : 0;
    const controller = new AbortController();
    const callerSignal = options?.signal ?? init.signal;
    const abort = () => controller.abort(callerSignal?.reason);
    if (callerSignal?.aborted) abort();
    else callerSignal?.addEventListener("abort", abort, { once: true });
    const deadline = Date.now() + (options?.timeoutMs ?? 30_000);
    const timer = setTimeout(() => controller.abort(
      new DOMException("Request timed out. Please try again.", "TimeoutError")
    ), Math.max(0, deadline - Date.now()));

    // Content-Type only accompanies a body: on a bodyless GET it is not a
    // CORS-safelisted header, so it would force a preflight for every read.
    const headers: Record<string, string> = {
      ...(init.body != null ? { "Content-Type": "application/json" } : {}),
      ...(init.headers as Record<string, string> || {}),
    };
    const sentToken = auth === "anonymous" ? null : this.token;
    if (sentToken) {
      headers["Authorization"] = `Bearer ${sentToken}`;
    }
    if (this.opsToken) {
      headers["X-Ops-Token"] = this.opsToken;
    }

    try {
      for (let attempt = 0; ; attempt += 1) {
        let retryAfter: string | null = null;
        try {
          controller.signal.throwIfAborted();
          const response = await fetch(url, {
            ...init,
            headers,
            signal: controller.signal,
          });
          retryAfter = response.headers.get("Retry-After");
          const payload = response.status === 204 ? null : await response.json().catch(() => null);
          controller.signal.throwIfAborted();
          if (!response.ok) {
            const failure = new ApiClientError(
              describeErrorPayload(payload, response.status), response.status, payload
            );
            if (
              response.status === 401 && auth === "session" && sentToken
              && sentToken === this.token && this.onUnauthorized
            ) {
              // A handler that throws must not mask the 401 the caller awaits.
              try { this.onUnauthorized(failure); } catch { /* ignore */ }
            }
            throw failure;
          }
          return { data: payload as T, response };
        } catch (error) {
          controller.signal.throwIfAborted();
          const retryable = error instanceof ApiClientError
            ? TRANSIENT_STATUSES.has(error.status)
            : error instanceof TypeError;
          if (attempt >= retries || !retryable) throw error;
          const seconds = retryAfter === null ? NaN : Number(retryAfter);
          const requestedDelay = Number.isFinite(seconds)
            ? seconds * 1000
            : retryAfter ? Date.parse(retryAfter) - Date.now() : NaN;
          const delay = Number.isFinite(requestedDelay)
            ? Math.max(0, requestedDelay)
            : 500 * 2 ** attempt;
          // A server asking us to wait beyond the deadline must not be retried early.
          if (delay >= deadline - Date.now()) throw error;
          await waitForRetry(delay, controller.signal);
        }
      }
    } finally {
      clearTimeout(timer);
      callerSignal?.removeEventListener("abort", abort);
    }
  }

  // Auth
  async register(payload: AuthRequest): Promise<AuthResponse> {
    return this.request<AuthResponse>("/auth/register", {
      method: "POST",
      body: JSON.stringify(payload),
      auth: "anonymous",
    });
  }

  async login(payload: AuthRequest): Promise<AuthResponse> {
    return this.request<AuthResponse>("/auth/login", {
      method: "POST",
      body: JSON.stringify(payload),
      auth: "anonymous",
    });
  }

  /**
   * Ask for a password-reset link. The API answers 202 with the same neutral
   * message whether or not the address has an account.
   */
  async requestPasswordReset(email: string): Promise<DetailResponse> {
    return this.request<DetailResponse>("/auth/password-reset/request", {
      method: "POST",
      body: JSON.stringify({ email }),
      auth: "anonymous",
    });
  }

  /** Set a new password with an emailed token; answers like a login. */
  async confirmPasswordReset(payload: PasswordResetConfirmRequest): Promise<AuthResponse> {
    return this.request<AuthResponse>("/auth/password-reset/confirm", {
      method: "POST",
      body: JSON.stringify({ token: payload.token, new_password: payload.new_password }),
      auth: "anonymous",
    });
  }

  /**
   * Change the signed-in user's password. The response carries a NEW token;
   * every token issued before it stops working, so store the new one.
   */
  async changePassword(payload: ChangePasswordRequest): Promise<AuthResponse> {
    return this.request<AuthResponse>("/users/me/password", {
      method: "POST",
      body: JSON.stringify({
        current_password: payload.current_password,
        new_password: payload.new_password,
      }),
    });
  }

  /** Revoke every token issued to the account so far ("sign out everywhere"). */
  async logoutEverywhere(): Promise<void> {
    await this.request<void>("/auth/logout", { method: "POST", auth: "silent" });
  }

  /** Everything the service stores about the signed-in user, as one JSON document. */
  async exportMyData(options?: RequestOptions): Promise<unknown> {
    return this.request<unknown>("/users/me/export", { cache: "no-store" }, options);
  }

  /** Permanently delete the signed-in account. Requires the current password. */
  async deleteAccount(payload: DeleteAccountRequest): Promise<void> {
    await this.request<void>("/users/me/delete", {
      method: "POST",
      body: JSON.stringify({ password: payload.password }),
    });
  }

  // Events
  private static buildEventsQuery(query: EventsQuery): string {
    const params = new URLSearchParams();
    Object.entries(query).forEach(([key, value]) => {
      if (value !== undefined && value !== null) {
        params.set(key, String(value));
      }
    });
    return params.toString() ? `?${params.toString()}` : "";
  }

  async getEvents(query: EventsQuery = {}, options?: RequestOptions): Promise<EventResponse[]> {
    return this.request<EventResponse[]>(
      `/events${TruthOfFunApiClient.buildEventsQuery(query)}`, undefined, options
    );
  }

  /**
   * Like getEvents, but also returns the total number of matches before
   * pagination (from the X-Total-Count header) so callers can page correctly.
   */
  async getEventsPage(query: EventsQuery = {}, options?: RequestOptions): Promise<EventsPage> {
    const { data, response } = await this.requestWithResponse<EventResponse[]>(
      `/events${TruthOfFunApiClient.buildEventsQuery(query)}`, undefined, options
    );
    const header = response.headers.get("X-Total-Count");
    const total = header === null ? null : Number.parseInt(header, 10);
    return {
      events: data,
      total: total !== null && Number.isFinite(total) ? total : null,
    };
  }

  async getEvent(eventId: number, options?: RequestOptions): Promise<EventDetailResponse> {
    return this.request<EventDetailResponse>(`/events/${seg(eventId)}`, undefined, options);
  }

  /**
   * URL of the public iCalendar download for one event. It is a plain link
   * target (`<a href>`), not something to fetch through this client.
   */
  eventCalendarUrl(eventId: number): string {
    return `${this.baseUrl}/events/${seg(eventId)}/calendar.ics`;
  }

  /** The five Bay Area regions with their cities and upcoming-event counts. */
  async getRegions(options?: RequestOptions): Promise<RegionsResponse> {
    return this.request<RegionsResponse>("/regions", undefined, options);
  }

  async getRecommendations(limit = 25, offset = 0, options?: RequestOptions): Promise<RecommendationResponse[]> {
    return this.request<RecommendationResponse[]>(
      `/recommendations?limit=${seg(limit)}&offset=${seg(offset)}`, undefined, options
    );
  }

  async submitOnboarding(payload: OnboardingRequest): Promise<OnboardingResponse> {
    return this.request<OnboardingResponse>("/users/me/onboarding", {
      method: "POST",
      body: JSON.stringify(payload),
    });
  }

  async updateInterests(payload: InterestRequest): Promise<InterestResponse> {
    return this.request<InterestResponse>("/users/me/interests", {
      method: "POST",
      body: JSON.stringify(payload),
    });
  }

  async setPreferences(payload: PreferencesRequest): Promise<InterestResponse> {
    return this.request<InterestResponse>("/users/me/preferences", {
      method: "PUT",
      body: JSON.stringify(payload),
    });
  }

  async buildItinerary(payload: ConciergeRequest): Promise<ConciergeResponse> {
    return this.request<ConciergeResponse>("/concierge/itinerary", {
      method: "POST",
      body: JSON.stringify(payload),
    });
  }

  async shareItinerary(
    payload: ShareItineraryRequest
  ): Promise<PortableItineraryResponse> {
    return this.request<PortableItineraryResponse>("/concierge/itinerary/share", {
      method: "POST",
      // Whitelist public metadata so a legacy caller's query cannot be sent.
      body: JSON.stringify({
        expires_in_days: payload.expires_in_days,
        intent: payload.intent,
        timeframe: payload.timeframe,
        geography: payload.geography,
        anchor_event_id: payload.anchor_event_id,
        origin: payload.origin,
        travel_mode: payload.travel_mode,
        stops: payload.stops,
      }),
    });
  }

  async getSharedItinerary(token: string, options?: RequestOptions): Promise<PortableItineraryResponse> {
    return this.request<PortableItineraryResponse>(
      `/shared/itineraries/${encodeURIComponent(token)}`, { cache: "no-store" }, options
    );
  }

  async getMyItineraries(limit = 25, offset = 0, options?: RequestOptions): Promise<SharedItinerarySummary[]> {
    return this.request<SharedItinerarySummary[]>(
      `/users/me/itineraries?limit=${seg(limit)}&offset=${seg(offset)}`, { cache: "no-store" }, options
    );
  }

  async revokeItinerary(token: string): Promise<void> {
    await this.request<void>(`/users/me/itineraries/${encodeURIComponent(token)}`, { method: "DELETE" });
  }

  // Health
  async getSourceHealth(): Promise<{ sources: SourceHealthEntry[] }> {
    return this.request<{ sources: SourceHealthEntry[] }>("/health/sources");
  }

  /** One call answering "is anything broken?" — see docs/operations.md. */
  async getHealthSummary(): Promise<HealthSummary> {
    return this.request<HealthSummary>("/health/summary");
  }

  // Folders
  async listFolders(options?: RequestOptions): Promise<FolderResponse[]> {
    return this.request<FolderResponse[]>("/folders", undefined, options);
  }

  async createFolder(name: string): Promise<FolderResponse> {
    return this.request<FolderResponse>("/folders", {
      method: "POST",
      body: JSON.stringify({ name }),
    });
  }

  async getFolder(folderId: number, options?: RequestOptions): Promise<FolderDetailResponse> {
    return this.request<FolderDetailResponse>(`/folders/${seg(folderId)}`, undefined, options);
  }

  async addFolderItem(folderId: number, eventId: number): Promise<FolderDetailResponse> {
    return this.request<FolderDetailResponse>(`/folders/${seg(folderId)}/items`, {
      method: "POST",
      body: JSON.stringify({ event_id: eventId }),
    });
  }

  async voteFolderItem(
    folderId: number,
    folderItemId: number,
    voteValue: number
  ): Promise<FolderDetailResponse> {
    return this.request<FolderDetailResponse>(`/folders/${seg(folderId)}/votes`, {
      method: "POST",
      body: JSON.stringify({ folder_item_id: folderItemId, vote_value: voteValue }),
    });
  }

  async createFolderInvite(folderId: number): Promise<InviteResponse> {
    return this.request<InviteResponse>(`/folders/${seg(folderId)}/invite`, {
      method: "POST",
    });
  }

  async revokeFolderInvite(folderId: number, inviteToken: string): Promise<void> {
    await this.request<void>(`/folders/${seg(folderId)}/invites/${seg(inviteToken)}`, {
      method: "DELETE",
    });
  }

  async acceptFolderInvite(inviteToken: string): Promise<FolderDetailResponse> {
    return this.request<FolderDetailResponse>(
      `/folders/invites/${seg(inviteToken)}/accept`,
      { method: "POST" }
    );
  }

  async getSharedFolder(token: string, options?: RequestOptions): Promise<FolderDetailResponse> {
    return this.request<FolderDetailResponse>(`/shared/folders/${seg(token)}`, undefined, options);
  }
}
