"use client";

import { useCallback, useState } from "react";
import type { EventResponse, EventsQuery } from "@truth-of-fun/api-client";
import { apiClient } from "@/lib/api/client";
import { markFirstResults } from "@/lib/ux-metrics";

export function useExploreEvents() {
  const [events, setEvents] = useState<EventResponse[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const loadEvents = useCallback(async (query: EventsQuery) => {
    setLoading(true);
    setError(null);
    try {
      const result = await apiClient.getEvents(query);
      setEvents(result);
      if (result.length > 0) {
        markFirstResults();
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : "Unknown error");
    } finally {
      setLoading(false);
    }
  }, []);

  return { events, loading, error, loadEvents };
}
