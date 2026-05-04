"use client";

import { useCallback, useEffect, useState } from "react";
import type { EventResponse, EventsQuery } from "@truth-of-fun/api-client";
import { apiClient } from "@/lib/api/client";
import { EventCard } from "@/components/event-card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Card } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { cn } from "@/lib/cn";

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
  "Music", "Sports", "Arts & Theatre", "Comedy", "Film", "Miscellaneous",
];

export default function ExplorePage() {
  const [events, setEvents] = useState<EventResponse[]>([]);
  const [loading, setLoading] = useState(true);
  const [searchText, setSearchText] = useState("");
  const [timePreset, setTimePreset] = useState("");
  const [locationPreset, setLocationPreset] = useState("");
  const [activeCategory, setActiveCategory] = useState("");
  const [page, setPage] = useState(0);
  const [hasMore, setHasMore] = useState(true);
  const PAGE_SIZE = 20;

  const fetchEvents = useCallback(async (reset: boolean) => {
    setLoading(true);
    const offset = reset ? 0 : page * PAGE_SIZE;
    try {
      const query: EventsQuery = { limit: PAGE_SIZE, offset };
      if (searchText.trim()) query.q = searchText.trim();
      if (timePreset) query.time_preset = timePreset as EventsQuery["time_preset"];
      if (locationPreset) query.location_preset = locationPreset as EventsQuery["location_preset"];

      const data = await apiClient.getEvents(query);
      if (reset) {
        setEvents(data);
        setPage(0);
      } else {
        setEvents((prev) => [...prev, ...data]);
      }
      setHasMore(data.length === PAGE_SIZE);
    } catch (err) {
      console.error("Failed to load events", err);
    } finally {
      setLoading(false);
    }
  }, [searchText, timePreset, locationPreset, page]);

  useEffect(() => {
    fetchEvents(true);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [timePreset, locationPreset]);

  function handleSearch(e: React.FormEvent) {
    e.preventDefault();
    fetchEvents(true);
  }

  function loadMore() {
    setPage((p) => p + 1);
  }

  useEffect(() => {
    if (page > 0) fetchEvents(false);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [page]);

  const displayed = activeCategory
    ? events.filter((e) => e.categories.some((c) => c.toLowerCase().includes(activeCategory.toLowerCase())))
    : events;

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
        <Button type="submit" disabled={loading}>Search</Button>
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

      <p className="text-sm text-slate-500">
        {loading && events.length === 0
          ? "Loading events..."
          : `${displayed.length} event${displayed.length !== 1 ? "s" : ""}`}
      </p>

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
      ) : (
        <>
          <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
            {displayed.map((event) => (
              <EventCard key={event.id} event={event} />
            ))}
          </div>
          {displayed.length === 0 && !loading && (
            <Card className="py-12 text-center">
              <p className="text-slate-400">No events found. Try adjusting your filters.</p>
            </Card>
          )}
          {hasMore && !activeCategory && (
            <div className="flex justify-center pt-2">
              <Button variant="secondary" onClick={loadMore} disabled={loading}>
                {loading ? "Loading..." : "Load more"}
              </Button>
            </div>
          )}
        </>
      )}
    </div>
  );
}
