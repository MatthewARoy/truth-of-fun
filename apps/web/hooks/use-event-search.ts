"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import type { EventResponse, EventsQuery } from "@truth-of-fun/api-client";
import { apiClient } from "@/lib/api/client";

const PAGE_SIZE = 20;

/** Each applied query owns its results and successful pagination cursor. */
export function useEventSearch(query: EventsQuery) {
  const key = JSON.stringify(query);
  const active = useRef<AbortController | null>(null);
  const [state, setState] = useState({
    key, events: [] as EventResponse[], nextOffset: 0,
    total: null as number | null, hasMore: false, loading: true, error: null as string | null,
  });

  const fetchPage = useCallback(async (offset: number) => {
    active.current?.abort();
    const controller = new AbortController();
    active.current = controller;
    setState((previous) => ({
      ...previous, key, loading: true, error: null,
      ...(offset === 0 ? { events: [], nextOffset: 0, total: null, hasMore: false } : {}),
    }));
    try {
      const page = await apiClient.getEventsPage(
        { ...query, limit: PAGE_SIZE, offset }, { signal: controller.signal }
      );
      if (controller.signal.aborted) return;
      const nextOffset = offset + page.events.length;
      setState((previous) => ({
        key,
        events: offset === 0 ? page.events : [...previous.events, ...page.events],
        nextOffset, total: page.total,
        hasMore: page.total === null ? page.events.length === PAGE_SIZE : nextOffset < page.total,
        loading: false, error: null,
      }));
    } catch (error) {
      if (controller.signal.aborted) return;
      setState((previous) => ({
        ...previous, loading: false,
        error: error instanceof Error ? error.message : "Could not load events.",
      }));
    }
  }, [key, query]);

  useEffect(() => {
    void fetchPage(0);
    return () => active.current?.abort();
  }, [fetchPage]);

  // Hide the prior query immediately, before its effect cleanup runs.
  const current = state.key === key ? state : {
    key, events: [], nextOffset: 0, total: null, hasMore: false, loading: true, error: null,
  };
  return { ...current, loadMore: () => {
    if (!current.loading) void fetchPage(current.nextOffset);
  } };
}
