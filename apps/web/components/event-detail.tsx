"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { ApiClientError, type EventDetailResponse } from "@truth-of-fun/api-client";
import { apiClient } from "@/lib/api/client";
import { useAuth } from "@/lib/auth-context";
import { cn } from "@/lib/cn";
import {
  directionsUrl, eventLongStartLabel, placeLabel, priceLabel, safeExternalUrl, safeImageUrl, statusNotice,
} from "@/lib/event-format";
import { formatLocalDay, formatLocalTime } from "@/lib/localtime";
import { CopyButton } from "@/components/copy-button";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { InlineNotice } from "@/components/ui/inline-notice";

const ACTION_LINK =
  "inline-flex items-center justify-center rounded-ui px-4 py-2 text-sm font-medium transition";

// One "viewed" signal per event per page session, however often React re-runs
// the effect (StrictMode) or the user navigates back to the same event.
const recordedViews = new Set<string>();

export function EventDetail({ event }: { event: EventDetailResponse }) {
  const { token } = useAuth();
  const [saveState, setSaveState] = useState<"idle" | "saving" | "saved">("idle");
  const [error, setError] = useState<string | null>(null);
  const [needsSignIn, setNeedsSignIn] = useState(false);
  const [imageFailed, setImageFailed] = useState(false);

  const notice = statusNotice(event.status);
  const price = priceLabel(event);
  const imageUrl = imageFailed ? null : safeImageUrl(event.image_url);
  const ticketsUrl = safeExternalUrl(event.external_url);
  const directions = directionsUrl(event);
  const description = event.description?.trim() ?? "";
  const categories = event.categories ?? [];
  const tags = event.tags ?? [];
  // A cancelled or postponed date is not one to put in a calendar.
  const canAddToCalendar = !notice;
  const address = event.raw_address?.trim();

  // Opening an event is the "viewed" signal that personalizes recommendations
  // for signed-in users. Anonymous visitors are not tracked.
  useEffect(() => {
    if (!token) return;
    const key = `${token}:${event.id}`;
    if (recordedViews.has(key)) return;
    recordedViews.add(key);
    void apiClient.updateInterests({ action: "click", event_id: event.id }).catch(() => {});
  }, [token, event.id]);

  async function handleSave() {
    if (!token) {
      setNeedsSignIn(true);
      return;
    }
    setSaveState("saving");
    setError(null);
    setNeedsSignIn(false);
    try {
      await apiClient.updateInterests({ action: "save", event_id: event.id });
      setSaveState("saved");
    } catch (err) {
      setSaveState("idle");
      if (err instanceof ApiClientError && err.status === 401) setNeedsSignIn(true);
      else setError(err instanceof Error ? err.message : "Could not save this event.");
    }
  }

  function trackTicketClick() {
    if (!token) return;
    void apiClient.updateInterests({ action: "external_ticket_click", event_id: event.id }).catch(() => {});
  }

  return (
    <article className="mx-auto max-w-3xl space-y-6">
      <p className="text-sm">
        <Link href="/explore">&larr; All events</Link>
      </p>

      {imageUrl ? (
        <div className="aspect-[16/9] w-full overflow-hidden rounded-ui border border-slate-800 bg-slate-900">
          {/* Hotlinked from the event's source: no referrer is sent. */}
          {/* eslint-disable-next-line @next/next/no-img-element */}
          <img
            src={imageUrl}
            alt=""
            decoding="async"
            referrerPolicy="no-referrer"
            className="h-full w-full object-cover"
            onError={() => setImageFailed(true)}
          />
        </div>
      ) : null}

      <header className="space-y-3">
        {notice ? (
          <div className={cn("rounded-ui border px-3 py-2 text-sm", notice.className)} role="status">
            <strong className="font-semibold">{notice.label}.</strong> {notice.explanation}
          </div>
        ) : null}
        <h1 className="break-words text-2xl font-semibold leading-tight sm:text-3xl">{event.title}</h1>
        {event.performers?.length ? (
          <p className="text-sm text-slate-400">With {event.performers.join(", ")}</p>
        ) : null}
      </header>

      <dl className="grid gap-x-6 gap-y-4 rounded-ui border border-slate-800 bg-slate-900 p-4 sm:grid-cols-2">
        <div className="space-y-1">
          <dt className="text-xs uppercase tracking-wider text-slate-400">{notice ? "Originally" : "When"}</dt>
          <dd className="text-sm text-slate-100" data-testid="event-when">
            {eventLongStartLabel(event)}
            {!event.start_time_is_estimated && event.end_at ? (
              <span className="text-slate-400">
                {" "}&ndash; ends {formatLocalDay(event.end_at)} {formatLocalTime(event.end_at)}
              </span>
            ) : null}
            <span className="block text-xs text-slate-400">
              {event.start_time_is_estimated
                ? "The source lists a date but no start time. Check with the organizer."
                : "Pacific time"}
            </span>
          </dd>
        </div>
        <div className="space-y-1">
          <dt className="text-xs uppercase tracking-wider text-slate-400">Where</dt>
          <dd className="text-sm text-slate-100" data-testid="event-where">
            {placeLabel(event)}
            {address ? <span className="block text-xs text-slate-400">{address}</span> : null}
          </dd>
        </div>
        <div className="space-y-1">
          <dt className="text-xs uppercase tracking-wider text-slate-400">Price</dt>
          <dd className="text-sm text-slate-100" data-testid="event-price">
            {price ?? <span className="text-slate-400">Not listed. Check the event page.</span>}
          </dd>
        </div>
        {event.organizer_name ? (
          <div className="space-y-1">
            <dt className="text-xs uppercase tracking-wider text-slate-400">Organizer</dt>
            <dd className="text-sm text-slate-100">{event.organizer_name}</dd>
          </div>
        ) : null}
      </dl>

      <div className="flex flex-wrap gap-2">
        {ticketsUrl ? (
          <a
            href={ticketsUrl}
            target="_blank"
            rel="noopener noreferrer"
            onClick={trackTicketClick}
            className={cn(ACTION_LINK, "bg-emerald-700 text-white hover:bg-emerald-600 hover:text-white")}
          >
            {price === "Free" ? "Event page" : "Tickets and info"}
          </a>
        ) : null}
        <Button type="button" onClick={() => void handleSave()} disabled={saveState !== "idle"}>
          {saveState === "saving" ? "Saving..." : saveState === "saved" ? "Saved" : "Save"}
        </Button>
        {canAddToCalendar ? (
          <a
            href={apiClient.eventCalendarUrl(event.id)}
            className={cn(ACTION_LINK, "bg-slate-800 text-slate-100 hover:bg-slate-700 hover:text-slate-100")}
          >
            Add to calendar
          </a>
        ) : null}
        {directions ? (
          <a
            href={directions}
            target="_blank"
            rel="noopener noreferrer"
            className={cn(ACTION_LINK, "bg-slate-800 text-slate-100 hover:bg-slate-700 hover:text-slate-100")}
          >
            Directions
          </a>
        ) : null}
        <CopyButton
          value={() => `${window.location.origin}/events/${event.id}`}
          label="Copy link"
          copiedLabel="Link copied"
        />
      </div>

      {needsSignIn ? (
        <InlineNotice tone="info">
          <Link href={`/login?next=${encodeURIComponent(`/events/${event.id}`)}`}>Sign in</Link> to save
          events and personalize your feed.
        </InlineNotice>
      ) : null}
      {saveState === "saved" ? <InlineNotice tone="success">Saved to your profile.</InlineNotice> : null}
      {error ? <InlineNotice tone="error">{error}</InlineNotice> : null}

      <section className="space-y-2" aria-labelledby="event-about">
        <h2 id="event-about" className="text-base font-semibold">About this event</h2>
        {description ? (
          <p className="whitespace-pre-line break-words text-sm leading-relaxed text-slate-300">{description}</p>
        ) : (
          <p className="text-sm text-slate-400">The source did not provide a description.</p>
        )}
      </section>

      {categories.length > 0 || tags.length > 0 ? (
        <section className="space-y-2" aria-labelledby="event-tags">
          <h2 id="event-tags" className="text-base font-semibold">Categories and tags</h2>
          <ul className="flex flex-wrap gap-2">
            {categories.map((category) => (
              <li key={`category-${category}`}><Badge active>{category}</Badge></li>
            ))}
            {tags.map((tag) => (
              <li key={`tag-${tag}`}><Badge>{tag}</Badge></li>
            ))}
          </ul>
        </section>
      ) : null}

      <p className="border-t border-slate-800 pt-4 text-xs text-slate-400">
        {event.source_name ? <>This listing comes from {event.source_name}. </> : null}
        {event.updated_at ? <>Details last refreshed {formatLocalDay(event.updated_at)}. </> : null}
        Times, prices and availability can change, so confirm with the organizer before you go.
      </p>
    </article>
  );
}
