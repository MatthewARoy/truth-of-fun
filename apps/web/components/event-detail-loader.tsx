"use client";

import { useCallback, useEffect, useState } from "react";
import { ApiClientError, type EventDetailResponse } from "@truth-of-fun/api-client";
import { apiClient } from "@/lib/api/client";
import { EventDetail } from "@/components/event-detail";
import { NotFoundContent } from "@/components/not-found-content";
import { Button } from "@/components/ui/button";
import { InlineNotice } from "@/components/ui/inline-notice";
import { Skeleton } from "@/components/ui/skeleton";

type State =
  | { status: "loading" }
  | { status: "ok"; event: EventDetailResponse }
  | { status: "missing" }
  | { status: "error"; message: string };

/**
 * Fallback for when the server could not reach the API while rendering the
 * event page: the browser fetches the event itself, so the page still works
 * (without the server-rendered share metadata).
 */
export function EventDetailLoader({ eventId }: { eventId: number }) {
  const [state, setState] = useState<State>({ status: "loading" });
  const [attempt, setAttempt] = useState(0);

  useEffect(() => {
    const controller = new AbortController();
    apiClient.getEvent(eventId, { signal: controller.signal })
      .then((event) => {
        if (!controller.signal.aborted) setState({ status: "ok", event });
      })
      .catch((error) => {
        if (controller.signal.aborted) return;
        if (error instanceof ApiClientError && (error.status === 404 || error.status === 422)) {
          setState({ status: "missing" });
        } else {
          setState({
            status: "error",
            message: error instanceof Error ? error.message : "This event could not be loaded.",
          });
        }
      });
    return () => controller.abort();
  }, [eventId, attempt]);

  const retry = useCallback(() => {
    setState({ status: "loading" });
    setAttempt((value) => value + 1);
  }, []);

  if (state.status === "ok") return <EventDetail event={state.event} />;
  if (state.status === "missing") {
    return (
      <NotFoundContent
        title="We couldn't find that event"
        message="It may have been removed, or the link may be out of date."
      />
    );
  }
  if (state.status === "error") {
    return (
      <section className="mx-auto max-w-3xl space-y-4">
        <h1 className="text-xl font-semibold">Event</h1>
        <InlineNotice tone="error">Could not load this event: {state.message}</InlineNotice>
        <Button type="button" variant="secondary" onClick={retry}>Retry</Button>
      </section>
    );
  }
  return (
    <section className="mx-auto max-w-3xl space-y-4" aria-busy="true" aria-label="Loading event">
      <Skeleton className="h-8 w-3/4" />
      <Skeleton className="h-5 w-1/2" />
      <Skeleton className="h-40 w-full" />
    </section>
  );
}
