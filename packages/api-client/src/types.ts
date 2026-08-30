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

/** Google Maps deep links for one stop. Null when the stop has no resolvable
 * location (no coordinates, address, or venue name). */
export type StopLinks = {
  tickets_url: string | null;
  map_url: string | null;
  /** Driving directions from the previous stop, or from current location for
   * the first one. */
  directions_url: string | null;
  food_url: string | null;
  drinks_url: string | null;
  parking_url: string | null;
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
  address: string | null;
  lat: number | null;
  lng: number | null;
  links: StopLinks;
};

export type ConciergeResponse = {
  intent: string;
  timeframe: string;
  geography: string | null;
  category_focus?: string | null;
  anchor_event_id: number | null;
  itinerary: ItineraryStopResponse[];
  /** Subject-line summary, e.g. "Date night in Mission — Sat, Aug 8". */
  title: string;
  /** Pasteable plain-text rendering of the whole plan. */
  text: string;
};

/** Only identity and ordering come from the client; the server re-reads every
 * display fact from the database when it writes the snapshot. */
export type ShareItineraryStop = {
  kind: string;
  event_id: number;
  travel_buffer_minutes_before?: number;
};

export type ShareItineraryRequest = {
  query?: string;
  intent?: string;
  timeframe?: string;
  geography?: string | null;
  anchor_event_id?: number | null;
  stops: ShareItineraryStop[];
};

export type PortableItineraryResponse = {
  share_token: string;
  /** Relative path to the public page, e.g. "/itinerary/<token>". */
  share_url: string;
  title: string;
  query: string;
  intent: string;
  timeframe: string;
  geography: string | null;
  anchor_event_id: number | null;
  created_at: string;
  itinerary: ItineraryStopResponse[];
  text: string;
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
  /** Radius search only. Defaults to 0.5 server-side, excluding city-centroid
   * fallbacks; pass 0 to include them. */
  min_location_confidence?: number;
  vibe_tag?: string;
  category?: string;
  time_preset?: "tonight" | "this_weekend";
  location_preset?: "sf" | "oakland" | "san_jose";
  sort_by?: "date" | "distance";
  start_at?: string;
  end_at?: string;
  limit?: number;
  offset?: number;
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
};
