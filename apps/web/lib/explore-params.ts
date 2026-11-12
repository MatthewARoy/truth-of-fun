import type { EventsQuery, RegionId } from "@truth-of-fun/api-client";
import { isDateKey, localDayRange } from "@/lib/localtime";

export const REGION_IDS: readonly RegionId[] = ["sf", "east_bay", "peninsula", "south_bay", "north_bay"];

/** Used until GET /regions answers, and if it never does. Mirrors the API's labels. */
export const FALLBACK_REGIONS: ReadonlyArray<{ id: RegionId; label: string }> = [
  { id: "sf", label: "San Francisco" },
  { id: "east_bay", label: "East Bay" },
  { id: "peninsula", label: "Peninsula" },
  { id: "south_bay", label: "South Bay" },
  { id: "north_bay", label: "North Bay" },
];

export const CATEGORY_FILTERS = [
  "Music", "Nightlife", "Fitness", "Wellness", "Outdoors", "Sports",
  "Comedy", "Arts & Theatre", "Film", "Food", "Social",
] as const;

export type TimePreset = "tonight" | "this_weekend";
export type ExploreView = "list" | "map";

/** Everything about an Explore search that lives in the URL. */
export type ExploreFilters = {
  q: string;
  when: TimePreset | "";
  /** First day of a custom range, YYYY-MM-DD in Pacific time. Wins over `when`. */
  date: string;
  /** Last day of the range; empty means the single day `date`. */
  to: string;
  region: RegionId | "";
  city: string;
  category: string;
  free: boolean;
  view: ExploreView;
};

export const EMPTY_FILTERS: ExploreFilters = {
  q: "", when: "", date: "", to: "", region: "", city: "", category: "", free: false, view: "list",
};

type Params = { get(name: string): string | null };

/** Read filters from a query string, ignoring anything unrecognised or malformed. */
export function parseExploreParams(params: Params): ExploreFilters {
  const when = params.get("when");
  const date = params.get("date");
  const to = params.get("to");
  const region = params.get("region");
  const validDate = isDateKey(date) ? date : "";
  const validRegion = REGION_IDS.includes(region as RegionId) ? (region as RegionId) : "";
  return {
    q: (params.get("q") ?? "").trim().slice(0, 200),
    when: !validDate && (when === "tonight" || when === "this_weekend") ? when : "",
    date: validDate,
    to: validDate && isDateKey(to) && to > validDate ? to : "",
    region: validRegion,
    // A city only narrows a region; on its own it would be ambiguous.
    city: validRegion ? (params.get("city") ?? "").trim().slice(0, 80) : "",
    category: (params.get("category") ?? "").trim().slice(0, 60),
    free: params.get("free") === "1",
    view: params.get("view") === "map" ? "map" : "list",
  };
}

/** The query string for a set of filters, with defaults omitted and a stable order. */
export function exploreSearch(filters: ExploreFilters): string {
  const params = new URLSearchParams();
  if (filters.q) params.set("q", filters.q);
  if (filters.date) {
    params.set("date", filters.date);
    if (filters.to && filters.to > filters.date) params.set("to", filters.to);
  } else if (filters.when) {
    params.set("when", filters.when);
  }
  if (filters.region) {
    params.set("region", filters.region);
    if (filters.city) params.set("city", filters.city);
  }
  if (filters.category) params.set("category", filters.category);
  if (filters.free) params.set("free", "1");
  if (filters.view === "map") params.set("view", "map");
  const text = params.toString();
  return text ? `?${text}` : "";
}

export type NearMe = { lat: number; lng: number; radiusMiles: number };

/** Translate URL filters (plus an optional "near me" position) into the API query. */
export function exploreEventsQuery(filters: ExploreFilters, near: NearMe | null): EventsQuery {
  return {
    q: filters.q || undefined,
    category: filters.category || undefined,
    is_free: filters.free ? true : undefined,
    ...(filters.date
      ? localDayRange(filters.date, filters.to || filters.date)
      : { time_preset: filters.when || undefined }),
    // "Near me" replaces the region filter rather than intersecting with it:
    // standing in Oakland with "San Francisco" selected would always be empty.
    ...(near
      ? { lat: near.lat, lng: near.lng, radius_miles: near.radiusMiles, sort_by: "distance" as const }
      : { region: filters.region || undefined, city: filters.city || undefined }),
  };
}

export function hasActiveFilters(filters: ExploreFilters): boolean {
  return Boolean(
    filters.q || filters.when || filters.date || filters.region || filters.category || filters.free
  );
}
