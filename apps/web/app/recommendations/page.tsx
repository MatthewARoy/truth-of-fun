"use client";

import { useEffect, useState } from "react";
import type { FolderResponse } from "@truth-of-fun/api-client";
import { EventCard } from "@/components/event-card";
import { Card } from "@/components/ui/card";
import { InlineNotice } from "@/components/ui/inline-notice";
import { useRecommendations } from "@/hooks/use-recommendations";
import { apiClient } from "@/lib/api/client";
import { useAuth } from "@/lib/auth-context";

export default function RecommendationsPage() {
  const { ready, token } = useAuth();
  if (!ready) return <InlineNotice>Loading recommendations...</InlineNotice>;
  if (!token) return (
    <section className="space-y-4">
      <h2 className="text-xl font-semibold">Recommendations</h2>
      <InlineNotice tone="info">Sign in to see personalized recommendations.</InlineNotice>
    </section>
  );
  return <SignedInRecommendations key={token} />;
}

function SignedInRecommendations() {
  const { items, loading, error, loadRecommendations } = useRecommendations();
  const [folders, setFolders] = useState<FolderResponse[]>([]);

  useEffect(() => {
    const controller = new AbortController();
    async function bootstrap() {
      await loadRecommendations(controller.signal);
      if (controller.signal.aborted) return;
      try {
        const response = await apiClient.listFolders({ signal: controller.signal });
        if (controller.signal.aborted) return;
        setFolders(response);
      } catch {
        // Page still functions if folder fetch fails.
      }
    }
    void bootstrap();
    return () => controller.abort();
  }, [loadRecommendations]);

  async function addEventToFolder(eventId: number, folderId: number) {
    await apiClient.addFolderItem(folderId, eventId);
  }

  return (
    <section className="space-y-4">
      <h2 className="text-xl font-semibold">Recommendations</h2>
      <Card className="space-y-2">
        <p className="text-sm text-slate-300">Personalized picks based on your onboarding and recent signals.</p>
      </Card>
      {loading ? <InlineNotice>Loading recommendations...</InlineNotice> : null}
      {error ? <InlineNotice tone="error">Error: {error}</InlineNotice> : null}
      {!loading && !error && items.length === 0 ? (
        <InlineNotice>No recommendations yet — try saving a few events first.</InlineNotice>
      ) : null}
      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
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
