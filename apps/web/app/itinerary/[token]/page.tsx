"use client";

import { useParams } from "next/navigation";
import { useCallback, useEffect, useRef, useState } from "react";
import type { PortableItineraryResponse } from "@truth-of-fun/api-client";
import { apiClient } from "@/lib/api/client";
import { CopyButton } from "@/components/copy-button";
import { ItinerarySteps } from "@/components/itinerary-steps";
import { Button } from "@/components/ui/button";
import { InlineNotice } from "@/components/ui/inline-notice";
import { Skeleton } from "@/components/ui/skeleton";
import { formatLocalDay, formatLocalTime } from "@/lib/localtime";

export default function SharedItineraryPage() {
  const params = useParams<{ token: string }>();
  return <SharedItinerary key={params.token} token={params.token} />;
}

function SharedItinerary({ token }: { token: string }) {
  const [itinerary, setItinerary] = useState<PortableItineraryResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const request = useRef<AbortController | null>(null);

  const load = useCallback(async () => {
    request.current?.abort();
    const controller = new AbortController();
    request.current = controller;
    setItinerary(null);
    setLoading(true);
    setError(null);
    try {
      const response = await apiClient.getSharedItinerary(token, { signal: controller.signal, retries: 0 });
      if (controller.signal.aborted) return;
      if (Date.parse(response.expires_at) <= Date.now()) throw new Error("This shared plan has expired.");
      setItinerary(response);
    } catch (err) {
      if (!controller.signal.aborted) setError(err instanceof Error ? err.message : "This itinerary could not be loaded");
    } finally {
      if (!controller.signal.aborted) setLoading(false);
    }
  }, [token]);

  useEffect(() => {
    void load();
    const refreshVisible = () => { if (document.visibilityState === "visible") void load(); };
    window.addEventListener("focus", refreshVisible);
    document.addEventListener("visibilitychange", refreshVisible);
    return () => {
      request.current?.abort();
      window.removeEventListener("focus", refreshVisible);
      document.removeEventListener("visibilitychange", refreshVisible);
    };
  }, [load]);

  useEffect(() => {
    if (!itinerary) return;
    // Thirty days exceeds the browser's maximum timer delay. Revalidate at
    // that limit, then schedule the remaining time from the returned expiry.
    const remaining = Math.max(0, Date.parse(itinerary.expires_at) - Date.now());
    const timer = window.setTimeout(() => void load(), Math.min(remaining, 2_147_483_647));
    return () => window.clearTimeout(timer);
  }, [itinerary, load]);

  return (
    <section className="mx-auto max-w-xl space-y-4">
      {loading && (
        <div className="space-y-3" aria-label="Loading shared plan">
          <Skeleton className="h-7 w-2/3" />
          <Skeleton className="h-28 w-full" />
          <Skeleton className="h-28 w-full" />
        </div>
      )}
      {error && (
        <>
          <InlineNotice tone="error">{error}</InlineNotice>
          <Button variant="secondary" onClick={() => void load()}>Retry</Button>
        </>
      )}
      {itinerary && (
        <>
          <header className="space-y-1">
            <h1 className="text-xl font-semibold">{itinerary.title}</h1>
            {itinerary.origin && <p className="text-sm text-slate-400">Starting point: {itinerary.origin.name || itinerary.origin.address || `${itinerary.origin.lat}, ${itinerary.origin.lng}`} · {itinerary.travel_mode ?? "driving"}</p>}
            <p className="text-sm text-slate-400">
              Public link expires {formatLocalDay(itinerary.expires_at)} at {formatLocalTime(itinerary.expires_at)} Pacific time.
            </p>
          </header>
          {itinerary.itinerary.length === 0 ? (
            <InlineNotice>This plan has no stops.</InlineNotice>
          ) : (
            <>
              <ItinerarySteps stops={itinerary.itinerary} showDayPerStop />
              <div className="flex flex-wrap gap-2 pt-2">
                <CopyButton value={itinerary.text} label="Copy as text" />
              </div>
              <p className="text-xs text-slate-600">
                Saved {formatLocalDay(itinerary.created_at)}. All times are local to the venue.
                Details are as of then &mdash; check the ticket links before you head out.
              </p>
            </>
          )}
        </>
      )}
    </section>
  );
}
