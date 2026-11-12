"use client";

import { useCallback, useMemo, useState } from "react";
import dynamic from "next/dynamic";
import { usePathname, useSearchParams } from "next/navigation";
import type { RegionId } from "@truth-of-fun/api-client";
import { useEventSearch } from "@/hooks/use-event-search";
import { useGeolocation } from "@/hooks/use-geolocation";
import { useRegions } from "@/hooks/use-regions";
import { EventCard } from "@/components/event-card";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Chip } from "@/components/ui/chip";
import { InlineNotice } from "@/components/ui/inline-notice";
import { Input } from "@/components/ui/input";
import { Select } from "@/components/ui/select";
import { Skeleton } from "@/components/ui/skeleton";
import { cn } from "@/lib/cn";
import {
  CATEGORY_FILTERS, EMPTY_FILTERS, exploreEventsQuery, exploreSearch, hasActiveFilters,
  parseExploreParams, type ExploreFilters, type NearMe,
} from "@/lib/explore-params";
import { formatDateKey, localDateKey } from "@/lib/localtime";

const EventMap = dynamic(
  () => import("@/components/event-map").then((m) => m.EventMap),
  { ssr: false, loading: () => <div className="h-[480px] rounded-ui border border-slate-800 bg-slate-900" /> }
);

const TIME_PRESETS = [
  { value: "", label: "Any time" },
  { value: "tonight", label: "Tonight" },
  { value: "this_weekend", label: "This weekend" },
] as const;

const RADIUS_OPTIONS = [1, 3, 5, 10] as const;
const DEFAULT_RADIUS = 5;

const GROUP_LABEL = "w-16 shrink-0 pt-1.5 text-xs uppercase tracking-wider text-slate-400";

export function ExploreClient() {
  const pathname = usePathname();
  const searchParams = useSearchParams();
  // The URL is the single source of truth for filters: every change is a
  // history entry, so back/forward, refresh and shared links all restore it.
  const filters = useMemo(() => parseExploreParams(searchParams), [searchParams]);

  const { regions } = useRegions();
  const geo = useGeolocation();
  const [radiusMiles, setRadiusMiles] = useState<number>(DEFAULT_RADIUS);
  const [selectedId, setSelectedId] = useState<number | null>(null);
  const [datesOpen, setDatesOpen] = useState(false);

  // The search box holds unsubmitted text; resync it when the applied query
  // changes underneath it (back/forward, "Clear filters").
  const [searchText, setSearchText] = useState(filters.q);
  const [syncedQuery, setSyncedQuery] = useState(filters.q);
  if (syncedQuery !== filters.q) {
    setSyncedQuery(filters.q);
    setSearchText(filters.q);
  }

  const near: NearMe | null = geo.state.status === "active"
    ? { lat: geo.state.lat, lng: geo.state.lng, radiusMiles }
    : null;
  const nearKey = near ? `${near.lat},${near.lng},${near.radiusMiles}` : "";
  const query = useMemo(
    () => exploreEventsQuery(filters, near),
    // `near` is rebuilt each render; its value is captured by nearKey.
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [filters, nearKey]
  );
  const { events, loading, error, total, hasMore, loadMore } = useEventSearch(query);

  const apply = useCallback((patch: Partial<ExploreFilters>) => {
    const next = { ...parseExploreParams(new URLSearchParams(window.location.search)), ...patch };
    const href = `${pathname}${exploreSearch(next)}`;
    if (href !== `${window.location.pathname}${window.location.search}`) {
      // Next.js keeps useSearchParams in sync with the native History API.
      window.history.pushState(null, "", href);
    }
    setSelectedId(null);
  }, [pathname]);

  function handleSearch(e: React.FormEvent) {
    e.preventDefault();
    apply({ q: searchText.trim() });
  }

  function chooseRegion(region: RegionId | "") {
    geo.clear();
    apply({ region, city: "" });
  }

  function toggleNearMe() {
    if (geo.state.status === "active" || geo.state.status === "locating") {
      geo.clear();
      return;
    }
    // Distance replaces the region filter, so drop it from the URL too.
    apply({ region: "", city: "" });
    geo.locate();
  }

  const today = localDateKey();
  const showDates = datesOpen || Boolean(filters.date);
  const dateChipLabel = filters.date
    ? filters.to
      ? `${formatDateKey(filters.date)} – ${formatDateKey(filters.to)}`
      : formatDateKey(filters.date)
    : "Pick dates";

  const selectedRegion = regions.find((region) => region.id === filters.region) ?? null;
  const cityOptions = selectedRegion?.cities ?? [];
  // Keep an applied city selectable even if /regions is down or no longer lists it.
  const cityKnown = !filters.city || cityOptions.some((city) => city.name === filters.city);
  const nearActive = geo.state.status === "active";

  const resultSummary = loading && events.length === 0
    ? "Loading events..."
    : total === null
      ? `${events.length.toLocaleString()} events loaded`
      : `${events.length.toLocaleString()} of ${total.toLocaleString()} events`;

  return (
    <div className="space-y-6">
      <form onSubmit={handleSearch} className="flex gap-2" role="search">
        <div className="flex-1">
          <Input
            type="search"
            name="q"
            aria-label="Search events"
            placeholder="Search events... (e.g. jazz, comedy, Warriors)"
            value={searchText}
            onChange={(e) => setSearchText(e.target.value)}
            maxLength={200}
            autoComplete="off"
          />
        </div>
        <Button type="submit">Search</Button>
      </form>

      <div className="space-y-3">
        <div className="flex gap-2" role="group" aria-label="When">
          <span className={GROUP_LABEL} aria-hidden="true">When</span>
          <div className="min-w-0 flex-1 space-y-2">
            <div className="flex flex-wrap gap-1.5">
              {TIME_PRESETS.map((preset) => (
                <Chip
                  key={preset.value}
                  pressed={!filters.date && filters.when === preset.value}
                  onClick={() => { setDatesOpen(false); apply({ when: preset.value, date: "", to: "" }); }}
                >
                  {preset.label}
                </Chip>
              ))}
              <Chip
                pressed={Boolean(filters.date)}
                aria-expanded={showDates}
                aria-controls="explore-dates"
                onClick={() => {
                  if (filters.date) {
                    setDatesOpen(false);
                    apply({ date: "", to: "" });
                  } else {
                    setDatesOpen((open) => !open);
                  }
                }}
              >
                {dateChipLabel}
              </Chip>
            </div>
            {showDates ? (
              <div id="explore-dates" className="flex flex-wrap items-end gap-3">
                <div className="w-40">
                  <Input
                    type="date"
                    label="Date"
                    name="date"
                    min={today}
                    value={filters.date}
                    onChange={(e) => {
                      const date = e.target.value;
                      apply({ when: "", date, to: date && filters.to > date ? filters.to : "" });
                    }}
                  />
                </div>
                <div className="w-40">
                  <Input
                    type="date"
                    label="Through (optional)"
                    name="to"
                    min={filters.date || today}
                    value={filters.to}
                    disabled={!filters.date}
                    onChange={(e) => apply({ to: e.target.value })}
                  />
                </div>
                <p className="pb-2 text-xs text-slate-400">Days are in Pacific time.</p>
              </div>
            ) : null}
          </div>
        </div>

        <div className="flex gap-2" role="group" aria-label="Where">
          <span className={GROUP_LABEL} aria-hidden="true">Where</span>
          <div className="min-w-0 flex-1 space-y-2">
            <div className="flex flex-wrap gap-1.5">
              <Chip pressed={!filters.region && !nearActive} onClick={() => chooseRegion("")}>
                Anywhere
              </Chip>
              {regions.map((region) => (
                <Chip
                  key={region.id}
                  pressed={!nearActive && filters.region === region.id}
                  onClick={() => chooseRegion(region.id)}
                  aria-label={
                    region.upcomingCount !== null
                      ? `${region.label}, ${region.upcomingCount.toLocaleString()} upcoming events`
                      : region.label
                  }
                >
                  {region.label}
                  {region.upcomingCount !== null ? (
                    <span className="ml-1.5 text-slate-400" data-testid={`region-count-${region.id}`}>
                      {region.upcomingCount.toLocaleString()}
                    </span>
                  ) : null}
                </Chip>
              ))}
              <Chip
                pressed={nearActive}
                onClick={toggleNearMe}
                disabled={geo.state.status === "locating"}
              >
                {geo.state.status === "locating" ? "Finding you..." : "Near me"}
              </Chip>
            </div>

            {filters.region && !nearActive && (cityOptions.length > 0 || filters.city) ? (
              <div className="w-full max-w-xs">
                <Select
                  label={`City in ${selectedRegion?.label ?? "this region"}`}
                  name="city"
                  value={filters.city}
                  onChange={(e) => apply({ city: e.target.value })}
                >
                  <option value="">All of {selectedRegion?.label ?? "this region"}</option>
                  {!cityKnown ? <option value={filters.city}>{filters.city}</option> : null}
                  {cityOptions.map((city) => (
                    <option key={city.name} value={city.name}>
                      {city.name} ({city.upcoming_count.toLocaleString()})
                    </option>
                  ))}
                </Select>
              </div>
            ) : null}

            {nearActive ? (
              <div className="flex flex-wrap items-end gap-3">
                <div className="w-40">
                  <Select
                    label="Within"
                    name="radius"
                    value={radiusMiles}
                    onChange={(e) => { setRadiusMiles(Number(e.target.value)); setSelectedId(null); }}
                  >
                    {RADIUS_OPTIONS.map((miles) => (
                      <option key={miles} value={miles}>{miles} {miles === 1 ? "mile" : "miles"}</option>
                    ))}
                  </Select>
                </div>
                <p className="pb-2 text-xs text-slate-400" role="status">
                  Showing events closest to you first. Your location is used for this search only and is
                  not saved.
                </p>
              </div>
            ) : null}
            {geo.state.status === "denied" ? (
              <InlineNotice tone="warning" role="alert">
                Location access is blocked for this site, so &ldquo;Near me&rdquo; can&apos;t work. Allow
                location in your browser&apos;s site settings and try again, or pick a region instead.
              </InlineNotice>
            ) : null}
            {geo.state.status === "unavailable" ? (
              <InlineNotice tone="warning" role="alert">
                We couldn&apos;t determine your location. Check that location services are on and try
                again, or pick a region instead.
              </InlineNotice>
            ) : null}
            {geo.state.status === "unsupported" ? (
              <InlineNotice tone="warning" role="alert">
                This browser doesn&apos;t offer location, so &ldquo;Near me&rdquo; isn&apos;t available. Pick a
                region instead.
              </InlineNotice>
            ) : null}
          </div>
        </div>

        <div className="flex gap-2" role="group" aria-label="Category">
          <span className={GROUP_LABEL} aria-hidden="true">What</span>
          <div className="flex min-w-0 flex-1 flex-wrap gap-1.5">
            <Chip pressed={!filters.category} onClick={() => apply({ category: "" })}>All</Chip>
            {CATEGORY_FILTERS.map((category) => (
              <Chip
                key={category}
                pressed={filters.category === category}
                onClick={() => apply({ category: filters.category === category ? "" : category })}
              >
                {category}
              </Chip>
            ))}
          </div>
        </div>

        <div className="flex gap-2" role="group" aria-label="Price">
          <span className={GROUP_LABEL} aria-hidden="true">Price</span>
          <div className="flex min-w-0 flex-1 flex-wrap items-center gap-1.5">
            <Chip pressed={filters.free} onClick={() => apply({ free: !filters.free })}>Free</Chip>
            {hasActiveFilters(filters) || nearActive ? (
              <button
                type="button"
                className="ml-auto text-xs text-brand-200 hover:text-brand-100 hover:underline"
                onClick={() => {
                  geo.clear();
                  setDatesOpen(false);
                  apply({ ...EMPTY_FILTERS, view: filters.view });
                }}
              >
                Clear filters
              </button>
            ) : null}
          </div>
        </div>
      </div>

      <div className="flex items-center justify-between gap-3">
        <p className="text-sm text-slate-400" role="status">{resultSummary}</p>
        <div className="flex gap-1 rounded-ui border border-slate-800 bg-slate-900 p-1" role="group" aria-label="View">
          {(["list", "map"] as const).map((option) => (
            <button
              key={option}
              type="button"
              onClick={() => apply({ view: option })}
              className={cn(
                "rounded-md px-3 py-1 text-xs transition",
                filters.view === option ? "bg-brand-500/20 text-brand-100" : "text-slate-400 hover:text-slate-200"
              )}
              aria-pressed={filters.view === option}
            >
              {option === "list" ? "List" : "Map"}
            </button>
          ))}
        </div>
      </div>

      {error ? (
        <InlineNotice tone="error">
          Could not load events: {error}{" "}
          <Button variant="ghost" size="sm" onClick={loadMore} disabled={loading}>Retry</Button>
        </InlineNotice>
      ) : null}
      {loading && events.length === 0 ? (
        <div className="grid items-stretch gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {Array.from({ length: 6 }).map((_, i) => (
            <Card key={i} className="space-y-3">
              <Skeleton className="h-5 w-3/4" />
              <Skeleton className="h-4 w-1/2" />
              <Skeleton className="h-4 w-full" />
            </Card>
          ))}
        </div>
      ) : filters.view === "map" ? (
        <EventMap
          events={events}
          selectedId={events.some((event) => event.id === selectedId) ? selectedId : null}
          onSelect={setSelectedId}
        />
      ) : (
        <>
          <div className="grid items-stretch gap-4 sm:grid-cols-2 lg:grid-cols-3">
            {events.map((event) => (
              <EventCard key={event.id} event={event} />
            ))}
          </div>
          {events.length === 0 && !loading && !error && (
            <Card className="py-12 text-center">
              <p className="text-slate-400">
                {nearActive
                  ? `No events found within ${radiusMiles} ${radiusMiles === 1 ? "mile" : "miles"} of you. Try a wider radius.`
                  : "No events found. Try adjusting your filters."}
              </p>
            </Card>
          )}
        </>
      )}
      {hasMore && !error && (
        <div className="flex justify-center pt-2">
          <Button variant="secondary" onClick={loadMore} disabled={loading}>
            {loading ? "Loading..." : "Load more"}
          </Button>
        </div>
      )}
    </div>
  );
}
