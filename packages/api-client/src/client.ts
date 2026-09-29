import type {
  AuthRequest,
  AuthResponse,
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

  constructor(baseUrl: string) {
    this.baseUrl = baseUrl.replace(/\/$/, "");
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
    init?: RequestInit,
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
    init?: RequestInit,
    options?: RequestOptions
  ): Promise<{ data: T; response: Response }> {
    const url = `${this.baseUrl}${path}`;
    const method = (init?.method || "GET").toUpperCase();
    const retryLimit = options?.retries ?? 1;
    const retries = method === "GET" && Number.isFinite(retryLimit)
      ? Math.min(3, Math.max(0, Math.floor(retryLimit))) : 0;
    const controller = new AbortController();
    const callerSignal = options?.signal ?? init?.signal;
    const abort = () => controller.abort(callerSignal?.reason);
    if (callerSignal?.aborted) abort();
    else callerSignal?.addEventListener("abort", abort, { once: true });
    const deadline = Date.now() + (options?.timeoutMs ?? 30_000);
    const timer = setTimeout(() => controller.abort(
      new DOMException("Request timed out. Please try again.", "TimeoutError")
    ), Math.max(0, deadline - Date.now()));

    const headers: Record<string, string> = {
      "Content-Type": "application/json",
      ...(init?.headers as Record<string, string> || {}),
    };
    if (this.token) {
      headers["Authorization"] = `Bearer ${this.token}`;
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
            const detail =
              typeof payload === "object" &&
              payload !== null &&
              "detail" in payload &&
              typeof (payload as { detail?: unknown }).detail === "string"
                ? (payload as { detail: string }).detail
                : `Request failed: ${response.status}`;
            throw new ApiClientError(detail, response.status, payload);
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
    });
  }

  async login(payload: AuthRequest): Promise<AuthResponse> {
    return this.request<AuthResponse>("/auth/login", {
      method: "POST",
      body: JSON.stringify(payload),
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

  async getEvent(eventId: number): Promise<EventDetailResponse> {
    return this.request<EventDetailResponse>(`/events/${eventId}`);
  }

  async getRecommendations(limit = 25, offset = 0, options?: RequestOptions): Promise<RecommendationResponse[]> {
    return this.request<RecommendationResponse[]>(
      `/recommendations?limit=${limit}&offset=${offset}`, undefined, options
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
      `/users/me/itineraries?limit=${limit}&offset=${offset}`, { cache: "no-store" }, options
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
    return this.request<FolderDetailResponse>(`/folders/${folderId}`, undefined, options);
  }

  async addFolderItem(folderId: number, eventId: number): Promise<FolderDetailResponse> {
    return this.request<FolderDetailResponse>(`/folders/${folderId}/items`, {
      method: "POST",
      body: JSON.stringify({ event_id: eventId }),
    });
  }

  async voteFolderItem(
    folderId: number,
    folderItemId: number,
    voteValue: number
  ): Promise<FolderDetailResponse> {
    return this.request<FolderDetailResponse>(`/folders/${folderId}/votes`, {
      method: "POST",
      body: JSON.stringify({ folder_item_id: folderItemId, vote_value: voteValue }),
    });
  }

  async createFolderInvite(folderId: number): Promise<InviteResponse> {
    return this.request<InviteResponse>(`/folders/${folderId}/invite`, {
      method: "POST",
    });
  }

  async revokeFolderInvite(folderId: number, inviteToken: string): Promise<void> {
    await this.request<void>(`/folders/${folderId}/invites/${inviteToken}`, {
      method: "DELETE",
    });
  }

  async acceptFolderInvite(inviteToken: string): Promise<FolderDetailResponse> {
    return this.request<FolderDetailResponse>(
      `/folders/invites/${inviteToken}/accept`,
      { method: "POST" }
    );
  }

  async getSharedFolder(token: string): Promise<FolderDetailResponse> {
    return this.request<FolderDetailResponse>(`/shared/folders/${token}`);
  }
}
