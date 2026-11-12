// Fixtures shared by the server-side mock API (mock-api-server.mjs) and the
// Playwright specs, so what the server renders and what the tests expect
// cannot drift apart.

export const SSR_EVENT = {
  id: 101,
  title: "Thundercat with the Oakland Symphony",
  description:
    "An evening of bass and strings at the Fox.\n\nDoors open one hour before the show. "
    + "All ages. <script>alert('listing markup must stay inert')</script>",
  start_at: "2026-12-05T04:00:00Z", // Fri, Dec 4 · 8:00 PM Pacific
  start_time_is_estimated: false,
  end_at: null,
  external_url: "https://tickets.example/thundercat",
  venue_name: "Fox Theater",
  tags: ["#LiveMusic", "#HighEnergy"],
  categories: ["Music"],
  performers: ["Thundercat"],
  image_url: "https://images.example/thundercat.jpg",
  price: 45,
  currency: "USD",
  status: "scheduled",
  people_interested: 3,
  distance_miles: null,
  lat: 37.8087,
  lng: -122.2703,
  organizer_name: "Another Planet Entertainment",
  attendee_count: 0,
  location_confidence: 1,
  is_free: false,
  city: "Oakland",
  region: "east_bay",
  first_seen_at: "2026-10-01T00:00:00Z",
  updated_at: "2026-11-10T18:00:00Z",
  source_name: "ticketmaster",
  source_tier: 1,
  raw_address: "1807 Telegraph Ave, Oakland, CA 94612",
};

// A free event whose source published a date but no start time.
export const SSR_ESTIMATED_EVENT = {
  ...SSR_EVENT,
  id: 102,
  title: "Sunday Streets: Valencia",
  description: "Car-free blocks, music and food.",
  start_at: "2026-12-06T20:00:00Z", // Sun, Dec 6 — the noon is a placeholder
  start_time_is_estimated: true,
  external_url: "javascript:alert(1)", // must never become a link
  venue_name: "Valencia Street",
  image_url: "http://insecure.example/streets.jpg", // not https: must not render
  performers: [],
  tags: [],
  categories: ["Outdoors"],
  price: null,
  is_free: true,
  city: "San Francisco",
  region: "sf",
  lat: 37.7749,
  lng: -122.4194,
  location_confidence: 0.2, // city-centroid fallback
  organizer_name: null,
  raw_address: null,
  source_name: "funcheap_sf",
};

export const SSR_CANCELLED_EVENT = {
  ...SSR_EVENT,
  id: 103,
  title: "Cancelled Comedy Night",
  status: "cancelled",
  image_url: null,
};

export const SSR_EVENTS = [SSR_EVENT, SSR_ESTIMATED_EVENT, SSR_CANCELLED_EVENT];

/** The server-side API answers 404 for this id. */
export const MISSING_EVENT_ID = 404;
/** The server-side API fails for ids at or above this, as if it were unreachable. */
export const UNREACHABLE_EVENT_ID_FROM = 9000;

export const SSR_PLAN_TOKEN = "ssr-plan-token-0000000000000000";
export const SSR_PLAN = {
  share_token: SSR_PLAN_TOKEN,
  share_url: `/itinerary/${SSR_PLAN_TOKEN}`,
  title: "Date night in Mission — Sat, Dec 5",
  intent: "date_night",
  timeframe: "this_saturday",
  geography: "mission",
  anchor_event_id: 2,
  created_at: "2026-11-01T00:00:00Z",
  expires_at: "2099-01-01T00:00:00Z",
  itinerary: [
    { title: "Happy hour at True Laurel" },
    { title: "Julien Baker at The Chapel" },
  ].map((stop, index) => ({
    kind: index === 0 ? "pre_event_drink" : "main_event",
    event_id: index + 1,
    title: stop.title,
    start_at: index === 0 ? "2026-12-06T01:30:00Z" : "2026-12-06T03:00:00Z",
    start_time_is_estimated: false,
    end_at: null,
    venue_name: null,
    external_url: null,
    travel_buffer_minutes_before: 0,
    address: null,
    lat: null,
    lng: null,
    links: { tickets_url: null, map_url: null, directions_url: null, food_url: null, drinks_url: null, parking_url: null },
  })),
  text: "Date night in Mission — Sat, Dec 5",
};

export const SSR_FOLDER_TOKEN = "ssr-folder-token";
export const SSR_FOLDER = {
  id: 9,
  name: "Birthday weekend ideas",
  share_token: SSR_FOLDER_TOKEN,
  items: [
    { folder_item_id: 1, event_id: 101, event_title: "Thundercat with the Oakland Symphony", vote_score: 2 },
    { folder_item_id: 2, event_id: 102, event_title: "Sunday Streets: Valencia", vote_score: 1 },
  ],
};
