"use client";

import { useParams } from "next/navigation";
import { useEffect, useState } from "react";
import type { PortableItineraryResponse } from "@truth-of-fun/api-client";
import { apiClient } from "@/lib/api/client";
import { CopyButton } from "@/components/copy-button";
import { ItinerarySteps } from "@/components/itinerary-steps";
import { InlineNotice } from "@/components/ui/inline-notice";
import { Skeleton } from "@/components/ui/skeleton";
import { LOCAL_TIME_ZONE } from "@/lib/localtime";

export default function SharedItineraryPage() {
  const params = useParams<{ token: string }>();
  const token = params.token;
  const [itinerary, setItinerary] = useState<PortableItineraryResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    async function load() {
      setLoading(true);
      setError(null);
      try {
        setItinerary(await apiClient.getSharedItinerary(token));
      } catch (err) {
        setError(
          err instanceof Error ? err.message : "This itinerary could not be loaded"
        );
      } finally {
        setLoading(false);
      }
    }
    if (token) void load();
  }, [token]);

  // Nothing here is behind auth, and the whole page is one column: it is meant
  // to be opened from a text message on a phone, mid-walk.
  return (
    <section className="mx-auto max-w-xl space-y-4">
      {loading && (
        <div className="space-y-3">
          <Skeleton className="h-7 w-2/3" />
          <Skeleton className="h-28 w-full" />
          <Skeleton className="h-28 w-full" />
        </div>
      )}

      {error && <InlineNotice tone="error">{error}</InlineNotice>}

      {itinerary && (
        <>
          <header className="space-y-1">
            <h1 className="text-xl font-semibold">{itinerary.title}</h1>
            {itinerary.query && (
              <p className="text-sm text-slate-500">&ldquo;{itinerary.query}&rdquo;</p>
            )}
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
                Saved{" "}
                {new Date(itinerary.created_at).toLocaleDateString(undefined, {
                  month: "short",
                  day: "numeric",
                  timeZone: LOCAL_TIME_ZONE,
                })}
                . All times are local to the venue. Details are as of then &mdash; check
                the ticket links before you head out.
              </p>
            </>
          )}
        </>
      )}
    </section>
  );
}
