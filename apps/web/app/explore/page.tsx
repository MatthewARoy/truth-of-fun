"use client";

import { useMemo, useState } from "react";
import dynamic from "next/dynamic";
import type { EventsQuery } from "@truth-of-fun/api-client";
import { useEventSearch } from "@/hooks/use-event-search";
import { EventCard } from "@/components/event-card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Card } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { InlineNotice } from "@/components/ui/inline-notice";
import { cn } from "@/lib/cn";

const EventMap = dynamic(
  () => import("@/components/event-map").then((m) => m.EventMap),
  { ssr: false, loading: () => <div className="h-[480px] rounded-ui border border-slate-800 bg-slate-900" /> }
);

type View = "list" | "map";

const TIME_PRESETS = [
  { value: "", label: "Any time" },
  { value: "tonight", label: "Tonight" },
  { value: "this_weekend", label: "This weekend" },
] as const;

const LOCATION_PRESETS = [
  { value: "", label: "Anywhere" },
  { value: "sf", label: "San Francisco" },
  { value: "oakland", label: "Oakland" },
  { value: "san_jose", label: "San Jose" },
] as const;

const CATEGORY_FILTERS = [
  "Music", "Nightlife", "Fitness", "Wellness", "Outdoors", "Sports",
  "Comedy", "Arts & Theatre", "Film", "Food", "Social",
];

export default function ExplorePage() {
  const [searchText, setSearchText] = useState("");
  const [appliedSearch, setAppliedSearch] = useState("");
  const [timePreset, setTimePreset] = useState("");
  const [locationPreset, setLocationPreset] = useState("");
  const [activeCategory, setActiveCategory] = useState("");
  const [view, setView] = useState<View>("list");
  const [selectedId, setSelectedId] = useState<number | null>(null);
  const query = useMemo<EventsQuery>(() => ({
    q: appliedSearch || undefined,
    time_preset: (timePreset || undefined) as EventsQuery["time_preset"],
    location_preset: (locationPreset || undefined) as EventsQuery["location_preset"],
    category: activeCategory || undefined,
  }), [appliedSearch, timePreset, locationPreset, activeCategory]);
  const { events, loading, error, hasMore, loadMore } = useEventSearch(query);

  function handleSearch(e: React.FormEvent) {
    e.preventDefault();
    setAppliedSearch(searchText.trim());
    setSelectedId(null);
  }

  // Category filtering is applied server-side, so pagination
  // stays correct — render whatever the API returned.
  const displayed = events;

  return (
    <div className="space-y-6">
      <form onSubmit={handleSearch} className="flex gap-2">
        <div className="flex-1">
          <Input
            placeholder="Search events... (e.g. jazz, comedy, Warriors)"
            value={searchText}
            onChange={(e) => setSearchText(e.target.value)}
          />
        </div>
        <Button type="submit">Search</Button>
      </form>

      <div className="flex flex-wrap gap-4">
        <div className="flex items-center gap-1.5">
          <span className="text-xs text-slate-500 uppercase tracking-wider">When</span>
          <div className="flex gap-1">
            {TIME_PRESETS.map((preset) => (
              <button
                key={preset.value}
                type="button"
                onClick={() => setTimePreset(preset.value)}
                className={cn(
                  "rounded-full px-3 py-1.5 text-xs transition",
                  timePreset === preset.value
                    ? "bg-brand-500/20 text-brand-100 border border-brand-400"
                    : "bg-slate-800/50 text-slate-400 border border-slate-700 hover:border-slate-600"
                )}
              >
                {preset.label}
              </button>
            ))}
          </div>
        </div>

        <div className="flex items-center gap-1.5">
          <span className="text-xs text-slate-500 uppercase tracking-wider">Where</span>
          <div className="flex gap-1">
            {LOCATION_PRESETS.map((preset) => (
              <button
                key={preset.value}
                type="button"
                onClick={() => setLocationPreset(preset.value)}
                className={cn(
                  "rounded-full px-3 py-1.5 text-xs transition",
                  locationPreset === preset.value
                    ? "bg-brand-500/20 text-brand-100 border border-brand-400"
                    : "bg-slate-800/50 text-slate-400 border border-slate-700 hover:border-slate-600"
                )}
              >
                {preset.label}
              </button>
            ))}
          </div>
        </div>
      </div>

      <div className="flex flex-wrap gap-1.5">
        <button
          type="button"
          onClick={() => setActiveCategory("")}
          className={cn(
            "rounded-full px-3 py-1.5 text-xs transition",
            !activeCategory
              ? "bg-brand-500/20 text-brand-100 border border-brand-400"
              : "bg-slate-800/50 text-slate-400 border border-slate-700 hover:border-slate-600"
          )}
        >
          All
        </button>
        {CATEGORY_FILTERS.map((cat) => (
          <button
            key={cat}
            type="button"
            onClick={() => setActiveCategory(activeCategory === cat ? "" : cat)}
            className={cn(
              "rounded-full px-3 py-1.5 text-xs transition",
              activeCategory === cat
                ? "bg-brand-500/20 text-brand-100 border border-brand-400"
                : "bg-slate-800/50 text-slate-400 border border-slate-700 hover:border-slate-600"
            )}
          >
            {cat}
          </button>
        ))}
      </div>

      <div className="flex items-center justify-between">
        <p className="text-sm text-slate-500">
          {loading && events.length === 0
            ? "Loading events..."
            : `${displayed.length} event${displayed.length !== 1 ? "s" : ""}`}
        </p>
        <div className="flex gap-1 rounded-ui border border-slate-800 bg-slate-900 p-1">
          <button
            type="button"
            onClick={() => setView("list")}
            className={cn(
              "rounded-md px-3 py-1 text-xs transition",
              view === "list" ? "bg-brand-500/20 text-brand-100" : "text-slate-400 hover:text-slate-200"
            )}
            aria-pressed={view === "list"}
          >
            List
          </button>
          <button
            type="button"
            onClick={() => setView("map")}
            className={cn(
              "rounded-md px-3 py-1 text-xs transition",
              view === "map" ? "bg-brand-500/20 text-brand-100" : "text-slate-400 hover:text-slate-200"
            )}
            aria-pressed={view === "map"}
          >
            Map
          </button>
        </div>
      </div>

      {error ? (
        <InlineNotice tone="error">
          Could not load events: {error}{" "}
          <Button variant="ghost" size="sm" onClick={loadMore} disabled={loading}>Retry</Button>
        </InlineNotice>
      ) : null}
      {loading && events.length === 0 ? (
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {Array.from({ length: 6 }).map((_, i) => (
            <Card key={i} className="space-y-3">
              <Skeleton className="h-5 w-3/4" />
              <Skeleton className="h-4 w-1/2" />
              <Skeleton className="h-4 w-full" />
            </Card>
          ))}
        </div>
      ) : view === "map" ? (
        <EventMap
          events={displayed}
          selectedId={displayed.some((event) => event.id === selectedId) ? selectedId : null}
          onSelect={(id) => setSelectedId(id)}
        />
      ) : (
        <>
          <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
            {displayed.map((event) => (
              <EventCard key={event.id} event={event} />
            ))}
          </div>
          {displayed.length === 0 && !loading && !error && (
            <Card className="py-12 text-center">
              <p className="text-slate-400">No events found. Try adjusting your filters.</p>
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
