"use client";

import { useMemo, useState } from "react";
import type { EventResponse } from "@truth-of-fun/api-client";
import { apiClient } from "@/lib/api/client";
import { markFirstSave } from "@/lib/ux-metrics";
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

export function EventCard({ event, showRecommendationFields, folderOptions = [], onAddToFolder }: Props) {
  const [status, setStatus] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busyAction, setBusyAction] = useState<string | null>(null);
  const [selectedFolderId, setSelectedFolderId] = useState<string>("");

  const startLabel = useMemo(() => new Date(event.start_at).toLocaleString(), [event.start_at]);

  async function handleAction(action: "save" | "click" | "external_ticket_click") {
    setBusyAction(action);
    setError(null);
    try {
      await apiClient.updateInterests({ action, event_id: event.id });
      if (action === "save") {
        markFirstSave();
      }
      setStatus(
        action === "save"
          ? "Saved to your profile."
          : action === "click"
            ? "Marked as viewed."
            : "Tracked ticket click."
      );
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not update event action.");
    } finally {
      setBusyAction(null);
    }
  }

  async function handleLike(tag: string) {
    setBusyAction(`like-${tag}`);
    setError(null);
    try {
      await apiClient.updateInterests({ action: "like", vibe_tag: tag });
      setStatus(`Added ${tag} to your preferences.`);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not update preferences.");
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
    <Card padding="none" className="flex flex-col">
      {event.image_url ? (
        <div className="relative aspect-[16/9] w-full overflow-hidden bg-slate-800">
          {/* eslint-disable-next-line @next/next/no-img-element */}
          <img
            src={event.image_url}
            alt={event.title}
            loading="lazy"
            className="h-full w-full object-cover transition-transform duration-300 hover:scale-105"
            onError={(e) => {
              const parent = e.currentTarget.parentElement;
              if (parent) parent.style.display = "none";
            }}
          />
          {showRecommendationFields ? (
            <div className="absolute right-2 top-2 rounded-full bg-brand-500/90 px-2.5 py-1 text-xs font-semibold text-white shadow-lg backdrop-blur">
              {showRecommendationFields.matchScore}% match
            </div>
          ) : null}
        </div>
      ) : null}
      <div className="flex flex-1 flex-col gap-3 p-4">
      <div className="space-y-1">
        <h3 className="text-lg font-semibold">{event.title}</h3>
        <p className="text-sm text-slate-300">
          {startLabel} at {event.venue_name || "Unknown venue"}
        </p>
      </div>

      <p className="text-sm text-slate-300 line-clamp-3">{event.description || "No description available."}</p>

      {event.friends_interested > 0 ? (
        <p className="text-sm text-slate-400">Friends interested: {event.friends_interested}</p>
      ) : null}

      {showRecommendationFields && !event.image_url ? (
        <div className="flex flex-wrap items-center gap-2 text-xs text-brand-200">
          <Badge active>Match {showRecommendationFields.matchScore}</Badge>
        </div>
      ) : null}
      {showRecommendationFields && showRecommendationFields.matchedVibes.length > 0 ? (
        <p className="text-xs text-brand-200">
          Matched: {showRecommendationFields.matchedVibes.join(", ")}
        </p>
      ) : null}

      <div className="flex flex-wrap items-center gap-2">
        {(event.tags || []).slice(0, 4).map((tag) => (
          <Button
            key={tag}
            type="button"
            onClick={() => handleLike(tag)}
            variant="ghost"
            size="sm"
            disabled={busyAction === `like-${tag}`}
          >
            {tag}
          </Button>
        ))}
      </div>

      <div className="flex flex-wrap gap-2">
        <Button
          type="button"
          onClick={() => handleAction("click")}
          variant="secondary"
          size="sm"
          disabled={busyAction !== null}
        >
          {busyAction === "click" ? "Saving..." : "Viewed"}
        </Button>
        <Button
          type="button"
          onClick={() => handleAction("save")}
          size="sm"
          disabled={busyAction !== null}
        >
          {busyAction === "save" ? "Saving..." : "Save"}
        </Button>
        {event.external_url ? (
          <a
            href={event.external_url}
            target="_blank"
            rel="noreferrer"
            onClick={() => handleAction("external_ticket_click")}
            className="rounded-ui bg-emerald-800 px-3 py-1.5 text-sm text-emerald-100 transition hover:bg-emerald-700"
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

      {status ? <InlineNotice tone="success">{status}</InlineNotice> : null}
      {error ? <InlineNotice tone="error">{error}</InlineNotice> : null}
      </div>
    </Card>
  );
}
