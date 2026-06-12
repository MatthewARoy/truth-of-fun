import type {
  AuthRequest,
  AuthResponse,
  ConciergeRequest,
  ConciergeResponse,
  EventResponse,
  EventsQuery,
  FolderDetailResponse,
  FolderResponse,
  InterestRequest,
  InterestResponse,
  InviteResponse,
  OnboardingRequest,
  OnboardingResponse,
  RecommendationResponse,
  SourceHealthEntry,
} from "./types";

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

type RequestOptions = {
  retries?: number;
};

export class TruthOfFunApiClient {
  private readonly baseUrl: string;
  private token: string | null = null;

  constructor(baseUrl: string) {
    this.baseUrl = baseUrl.replace(/\/$/, "");
  }

  setToken(token: string | null) {
    this.token = token;
  }

  getToken(): string | null {
    return this.token;
  }

  private async request<T>(
    path: string,
    init?: RequestInit,
    options?: RequestOptions
  ): Promise<T> {
    const url = `${this.baseUrl}${path}`;
    const method = (init?.method || "GET").toUpperCase();
    const retries = method === "GET" ? Math.max(0, options?.retries ?? 1) : 0;
    let attempts = 0;
    let lastError: unknown;

    const headers: Record<string, string> = {
      "Content-Type": "application/json",
      ...(init?.headers as Record<string, string> || {}),
    };
    if (this.token) {
      headers["Authorization"] = `Bearer ${this.token}`;
    }

    while (attempts <= retries) {
      try {
        const response = await fetch(url, {
          ...init,
          headers,
        });
        const payload = await response.json().catch(() => null);
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
        return payload as T;
      } catch (error) {
        lastError = error;
        if (attempts >= retries) {
          throw lastError;
        }
      }
      attempts += 1;
    }

    throw lastError;
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
  async getEvents(query: EventsQuery = {}): Promise<EventResponse[]> {
    const params = new URLSearchParams();
    Object.entries(query).forEach(([key, value]) => {
      if (value !== undefined && value !== null) {
        params.set(key, String(value));
      }
    });
    const suffix = params.toString() ? `?${params.toString()}` : "";
    return this.request<EventResponse[]>(`/events${suffix}`);
  }

  async getRecommendations(limit = 25, offset = 0): Promise<RecommendationResponse[]> {
    return this.request<RecommendationResponse[]>(
      `/recommendations?limit=${limit}&offset=${offset}`
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

  async buildItinerary(payload: ConciergeRequest): Promise<ConciergeResponse> {
    return this.request<ConciergeResponse>("/concierge/itinerary", {
      method: "POST",
      body: JSON.stringify(payload),
    });
  }

  // Health
  async getSourceHealth(): Promise<{ sources: SourceHealthEntry[] }> {
    return this.request<{ sources: SourceHealthEntry[] }>("/health/sources");
  }

  // Folders
  async listFolders(): Promise<FolderResponse[]> {
    return this.request<FolderResponse[]>("/folders");
  }

  async createFolder(name: string): Promise<FolderResponse> {
    return this.request<FolderResponse>("/folders", {
      method: "POST",
      body: JSON.stringify({ name }),
    });
  }

  async getFolder(folderId: number): Promise<FolderDetailResponse> {
    return this.request<FolderDetailResponse>(`/folders/${folderId}`);
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
