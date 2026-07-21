export type EventResponse = {
  id: number;
  title: string;
  description: string | null;
  start_at: string;
  end_at: string | null;
  external_url: string | null;
  venue_name: string | null;
  tags: string[];
  categories: string[];
  image_url: string | null;
  price: number | null;
  currency: string | null;
  status: string;
  people_interested: number;
  distance_miles?: number | null;
  lat?: number | null;
  lng?: number | null;
  organizer_name?: string | null;
  attendee_count?: number;
  location_confidence?: number;
  is_free?: boolean;
};

/**
 * GET /events/{id}. Adds the provenance an agent needs to cite an event.
 *
 * `first_seen_at` is when this platform ingested the event, NOT when it was
 * announced. Never present it as an announcement date.
 */
export type EventDetailResponse = EventResponse & {
  first_seen_at: string;
  updated_at: string;
  source_name: string;
  source_tier: number;
  raw_address?: string | null;
};

export type RecommendationResponse = EventResponse & {
  match_score: number;
  matched_vibes: string[];
};

export type OnboardingRequest = {
  perfect_saturday: string;
};

export type OnboardingResponse = {
  user_id: number;
  extracted_vibes: string[];
  preferred_vibes: string[];
};

export type InterestAction = "save" | "like" | "click" | "external_ticket_click";

export type InterestRequest = {
  action: InterestAction;
  event_id?: number;
  vibe_tag?: string;
};

export type InterestResponse = {
  user_id: number;
  saved_event_ids: number[];
  preferred_vibes: string[];
};

export type ConciergeRequest = {
  query: string;
  limit?: number;
};

export type ItineraryStopResponse = {
  kind: string;
  event_id: number;
  title: string;
  start_at: string;
  end_at: string | null;
  venue_name: string | null;
  external_url: string | null;
  travel_buffer_minutes_before: number;
};

export type ConciergeResponse = {
  intent: string;
  timeframe: string;
  geography: string | null;
  anchor_event_id: number | null;
  itinerary: ItineraryStopResponse[];
};

export type FolderResponse = {
  id: number;
  name: string;
  share_token: string;
  created_at: string;
};

export type FolderItemResponse = {
  folder_item_id: number;
  event_id: number;
  event_title: string;
  vote_score: number;
};

export type FolderDetailResponse = {
  id: number;
  name: string;
  share_token: string;
  items: FolderItemResponse[];
};

export type InviteResponse = {
  folder_id: number;
  invite_token: string;
  share_url: string;
  expires_at: string | null;
};

export type EventsQuery = {
  q?: string;
  lat?: number;
  lng?: number;
  radius_miles?: number;
  vibe_tag?: string;
  time_preset?: "tonight" | "this_weekend";
  location_preset?: "sf" | "oakland" | "san_jose";
  sort_by?: "date" | "distance";
  start_at?: string;
  end_at?: string;
  include_past?: boolean;
  status?: string;
  limit?: number;
  offset?: number;
};

/** A page of events plus the total number of matches before pagination. */
export type EventsPage = {
  events: EventResponse[];
  /** From the X-Total-Count header; null if the server omitted it. */
  total: number | null;
};

export type AuthRequest = {
  email: string;
  password: string;
};

export type AuthResponse = {
  access_token: string;
  token_type: string;
  user_id: number;
  email: string;
};

export type SourceHealthEntry = {
  name: string;
  status: "healthy" | "degraded" | "failing" | "unknown";
  last_run_at: string | null;
  last_event_count: number | null;
  consecutive_zeros: number;
  /** Exception text from the last failed fetch; null once the source recovers. */
  last_error?: string | null;
  last_error_at?: string | null;
  last_success_at?: string | null;
  /** No completed run recently — the worker may be stopped. */
  is_stale?: boolean;
};

/** GET /health/summary — every health signal rolled into one verdict. */
export type HealthSummary = {
  status: "ok" | "degraded" | "failing";
  checked_at: string;
  /** Human-readable, each naming its subsystem. Empty when status is "ok". */
  problems: string[];
  database: { connected: boolean };
  sources: {
    total: number;
    by_status: Record<string, number>;
    stale: number;
    worker_stalled: boolean;
  };
  events: {
    total_events?: number;
    upcoming_events?: number;
    newest_event_first_seen_at?: string | null;
  };
};
