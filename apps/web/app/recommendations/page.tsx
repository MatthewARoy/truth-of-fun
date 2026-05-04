"use client";

import { useEffect, useState } from "react";
import type { FolderResponse } from "@truth-of-fun/api-client";
import { EventCard } from "@/components/event-card";
import { Card } from "@/components/ui/card";
import { InlineNotice } from "@/components/ui/inline-notice";
import { useRecommendations } from "@/hooks/use-recommendations";
import { apiClient } from "@/lib/api/client";
import { readTimeToValueSeconds } from "@/lib/ux-metrics";

export default function RecommendationsPage() {
  const { items, loading, error, loadRecommendations } = useRecommendations();
  const [folders, setFolders] = useState<FolderResponse[]>([]);
  const [metrics, setMetrics] = useState<{ toResults: number | null; toFirstSave: number | null } | null>(null);

  useEffect(() => {
    async function bootstrap() {
      await loadRecommendations();
      try {
        const response = await apiClient.listFolders();
        setFolders(response);
      } catch {
        // Page still functions if folder fetch fails.
      }
      setMetrics(readTimeToValueSeconds());
    }
    void bootstrap();
  }, [loadRecommendations]);

  async function addEventToFolder(eventId: number, folderId: number) {
    await apiClient.addFolderItem(folderId, eventId);
  }

  return (
    <section className="space-y-4">
      <h2 className="text-xl font-semibold">Recommendations</h2>
      <Card className="space-y-2">
        <p className="text-sm text-slate-300">Personalized picks based on your onboarding and recent signals.</p>
        {metrics && (metrics.toResults || metrics.toFirstSave) ? (
          <p className="text-xs text-slate-400">
            Time-to-value:{" "}
            {[
              metrics.toResults ? `${metrics.toResults}s to first results` : null,
              metrics.toFirstSave ? `${metrics.toFirstSave}s to first save` : null,
            ]
              .filter(Boolean)
              .join(" | ")}
          </p>
        ) : null}
      </Card>
      {loading ? <InlineNotice>Loading recommendations...</InlineNotice> : null}
      {error ? <InlineNotice tone="error">Error: {error}</InlineNotice> : null}
      {!loading && !error && items.length === 0 ? <InlineNotice>No recommendations yet.</InlineNotice> : null}
      <div className="grid gap-3">
        {items.map((item) => (
          <EventCard
            key={item.id}
            event={item}
            showRecommendationFields={{
              matchScore: item.match_score,
              matchedVibes: item.matched_vibes,
            }}
            folderOptions={folders.map((folder) => ({ id: folder.id, name: folder.name }))}
            onAddToFolder={addEventToFolder}
          />
        ))}
      </div>
    </section>
  );
}
