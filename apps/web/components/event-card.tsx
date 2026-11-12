"use client";

import Link from "next/link";
import { useId, useState } from "react";
import { ApiClientError, type EventResponse } from "@truth-of-fun/api-client";
import { apiClient } from "@/lib/api/client";
import { useAuth } from "@/lib/auth-context";
import { cn } from "@/lib/cn";
import {
  distanceLabel, eventStartLabel, placeLabel, priceLabel, safeExternalUrl, safeImageUrl, statusNotice,
} from "@/lib/event-format";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { InlineNotice } from "@/components/ui/inline-notice";
import { Select } from "@/components/ui/select";

type Props = {
  event: EventResponse;
  showRecommendationFields?: {
    matchScore: number;
    matchedVibes: string[];
  };
  folderOptions?: Array<{ id: number; name: string }>;
  onAddToFolder?: (eventId: number, folderId: number) => Promise<void>;
};

// Roughly what three lines of card text hold; shorter descriptions need no toggle.
const LONG_DESCRIPTION = 150;

export function EventCard(props: Props) {
  const { token } = useAuth();
  return <EventCardContent key={token ?? "anonymous"} {...props} />;
}

function EventCardContent({ event, showRecommendationFields, folderOptions = [], onAddToFolder }: Props) {
  const { token } = useAuth();
  const descriptionId = useId();
  const [status, setStatus] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [needsSignIn, setNeedsSignIn] = useState(false);
  const [busyAction, setBusyAction] = useState<string | null>(null);
  const [selectedFolderId, setSelectedFolderId] = useState<string>("");
  const [expanded, setExpanded] = useState(false);
  const [imageFailed, setImageFailed] = useState(false);

  const startLabel = eventStartLabel(event);
  const notice = statusNotice(event.status);
  const price = priceLabel(event);
  const distance = distanceLabel(event.distance_miles);
  const imageUrl = imageFailed ? null : safeImageUrl(event.image_url);
  const ticketsUrl = safeExternalUrl(event.external_url);
  const description = event.description?.trim() ?? "";
  const canExpand = description.length > LONG_DESCRIPTION || description.includes("\n");
  const detailHref = `/events/${event.id}`;

  function isAuthError(err: unknown): boolean {
    return err instanceof ApiClientError && err.status === 401;
  }

  async function handleSave() {
    if (!token) {
      // Anonymous visitors get a sign-in prompt instead of a backend error.
      setStatus(null);
      setError(null);
      setNeedsSignIn(true);
      return;
    }
    setBusyAction("save");
    setError(null);
    setNeedsSignIn(false);
    try {
      await apiClient.updateInterests({ action: "save", event_id: event.id });
      setStatus("Saved to your profile.");
    } catch (err) {
      if (isAuthError(err)) {
        setNeedsSignIn(true);
      } else {
        setError(err instanceof Error ? err.message : "Could not save this event.");
      }
    } finally {
      setBusyAction(null);
    }
  }

  // Interest in tickets is recorded quietly for signed-in users; it must never
  // delay or block the link, and anonymous visitors are not tracked at all.
  function trackTicketClick() {
    if (!token) return;
    void apiClient.updateInterests({ action: "external_ticket_click", event_id: event.id }).catch(() => {});
  }

  async function handleLike(tag: string) {
    if (!token) {
      setStatus(null);
      setError(null);
      setNeedsSignIn(true);
      return;
    }
    setBusyAction(`like-${tag}`);
    setError(null);
    setNeedsSignIn(false);
    try {
      await apiClient.updateInterests({ action: "like", vibe_tag: tag });
      setStatus(`Added ${tag} to your preferences.`);
    } catch (err) {
      if (isAuthError(err)) {
        setNeedsSignIn(true);
      } else {
        setError(err instanceof Error ? err.message : "Could not update preferences.");
      }
    } finally {
      setBusyAction(null);
    }
  }

  async function handleAddToFolder() {
    if (!onAddToFolder || !selectedFolderId) {
      return;
    }
    setBusyAction("folder");
    setError(null);
    try {
      await onAddToFolder(event.id, Number(selectedFolderId));
      setStatus("Added to folder.");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not add event to folder.");
    } finally {
      setBusyAction(null);
    }
  }

  return (
    <Card padding="none" className="flex h-full min-w-0 flex-col">
      {imageUrl ? (
        <div className="relative aspect-[16/9] w-full overflow-hidden bg-slate-800">
          {/* Hotlinked from the event's source: no referrer, never blocks layout. */}
          {/* eslint-disable-next-line @next/next/no-img-element */}
          <img
            src={imageUrl}
            alt=""
            loading="lazy"
            decoding="async"
            referrerPolicy="no-referrer"
            className="h-full w-full object-cover"
            onError={() => setImageFailed(true)}
          />
          {showRecommendationFields ? (
            <div className="absolute right-2 top-2 rounded-full bg-brand-500/90 px-2.5 py-1 text-xs font-semibold text-white shadow-lg backdrop-blur">
              Match score: {showRecommendationFields.matchScore}
            </div>
          ) : null}
        </div>
      ) : null}
      <article className="flex flex-1 flex-col gap-3 p-4">
        <div className="space-y-1">
          {notice ? (
            <span
              className={cn(
                "inline-flex items-center rounded-full border px-2.5 py-1 text-xs font-semibold",
                notice.className
              )}
            >
              {notice.label}
            </span>
          ) : null}
          <h2 title={event.title} className="line-clamp-2 break-words text-lg font-semibold">
            <Link href={detailHref} className="text-slate-100 hover:underline">
              {event.title}
            </Link>
          </h2>
          {event.performers?.length ? (
            <p className="line-clamp-1 text-xs text-slate-400" title={event.performers.join(", ")}>
              With {event.performers.join(", ")}
            </p>
          ) : null}
          <p className="text-sm text-slate-300">
            {notice ? "Originally " : null}
            {startLabel}
          </p>
          <p className="text-sm text-slate-300">{placeLabel(event)}</p>
          {price || distance ? (
            <p className="flex flex-wrap items-center gap-2 pt-1 text-xs">
              {price ? (
                <span
                  className={cn(
                    "rounded-full border px-2.5 py-0.5 font-medium",
                    price === "Free"
                      ? "border-emerald-700 bg-emerald-900/40 text-emerald-100"
                      : "border-slate-700 bg-slate-800 text-slate-200"
                  )}
                >
                  {price}
                </span>
              ) : null}
              {distance ? <span className="text-slate-400">{distance}</span> : null}
            </p>
          ) : null}
        </div>

        {description ? (
          <div className="space-y-1">
            <p
              id={descriptionId}
              className={cn("whitespace-pre-line break-words text-sm text-slate-300", !expanded && "line-clamp-3")}
            >
              {description}
            </p>
            {canExpand ? (
              <button
                type="button"
                className="text-xs font-medium text-brand-200 hover:text-brand-100 hover:underline"
                aria-expanded={expanded}
                aria-controls={descriptionId}
                onClick={() => setExpanded((value) => !value)}
              >
                {expanded ? "Show less" : "Show more"}
              </button>
            ) : null}
          </div>
        ) : (
          <p className="text-sm text-slate-500">No description provided.</p>
        )}

        {event.people_interested > 0 ? (
          <p className="text-sm text-slate-400">People interested: {event.people_interested}</p>
        ) : null}

        {showRecommendationFields && !imageUrl ? (
          <div className="flex flex-wrap items-center gap-2 text-xs text-brand-200">
            <Badge active>Match score: {showRecommendationFields.matchScore}</Badge>
          </div>
        ) : null}
        {showRecommendationFields && showRecommendationFields.matchedVibes.length > 0 ? (
          <p className="text-xs text-brand-200">
            Matched: {showRecommendationFields.matchedVibes.join(", ")}
          </p>
        ) : null}

        {(event.tags || []).length > 0 ? (
          <div className="flex flex-wrap items-center gap-2">
            {(event.tags || []).slice(0, 4).map((tag) => (
              <Button
                key={tag}
                type="button"
                onClick={() => handleLike(tag)}
                variant="ghost"
                size="sm"
                disabled={busyAction === `like-${tag}`}
                title={`Show me more like ${tag}`}
              >
                {tag}
              </Button>
            ))}
          </div>
        ) : null}

        <div className="mt-auto flex flex-wrap items-center gap-2">
          <Button
            type="button"
            onClick={() => void handleSave()}
            size="sm"
            disabled={busyAction !== null}
          >
            {busyAction === "save" ? "Saving..." : "Save"}
          </Button>
          <Link
            href={detailHref}
            aria-label={`Details for ${event.title}`}
            className="rounded-ui bg-slate-800 px-3 py-1.5 text-sm font-medium text-slate-100 transition hover:bg-slate-700 hover:text-slate-100"
          >
            Details
          </Link>
          {ticketsUrl ? (
            <a
              href={ticketsUrl}
              target="_blank"
              rel="noopener noreferrer"
              onClick={trackTicketClick}
              className="rounded-ui bg-emerald-800 px-3 py-1.5 text-sm font-medium text-emerald-100 transition hover:bg-emerald-700 hover:text-emerald-100"
            >
              Tickets
            </a>
          ) : null}
        </div>

        {folderOptions.length > 0 && onAddToFolder ? (
          <div className="flex flex-wrap items-end gap-2">
            <div className="min-w-40 flex-1">
              <Select
                aria-label={`Choose folder for ${event.title}`}
                value={selectedFolderId}
                onChange={(entry) => setSelectedFolderId(entry.target.value)}
              >
                <option value="">Add to folder...</option>
                {folderOptions.map((folder) => (
                  <option key={folder.id} value={folder.id}>
                    {folder.name}
                  </option>
                ))}
              </Select>
            </div>
            <Button
              type="button"
              variant="secondary"
              size="sm"
              onClick={() => void handleAddToFolder()}
              disabled={!selectedFolderId || busyAction !== null}
            >
              {busyAction === "folder" ? "Adding..." : "Add"}
            </Button>
          </div>
        ) : null}

        {needsSignIn ? (
          <InlineNotice tone="info">
            <Link href="/login">Sign in</Link> to save events and personalize your feed.
          </InlineNotice>
        ) : null}
        {status ? <InlineNotice tone="success">{status}</InlineNotice> : null}
        {error ? <InlineNotice tone="error">{error}</InlineNotice> : null}
      </article>
    </Card>
  );
}
