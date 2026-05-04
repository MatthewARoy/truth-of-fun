"use client";

import { useParams } from "next/navigation";
import { useEffect, useState } from "react";
import type { FolderDetailResponse } from "@truth-of-fun/api-client";
import { apiClient } from "@/lib/api/client";
import { Card } from "@/components/ui/card";
import { InlineNotice } from "@/components/ui/inline-notice";

export default function SharedFolderPage() {
  const params = useParams<{ token: string }>();
  const token = params.token;
  const [folder, setFolder] = useState<FolderDetailResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    async function load() {
      setLoading(true);
      setError(null);
      try {
        const response = await apiClient.getSharedFolder(token);
        setFolder(response);
      } catch (err) {
        setError(err instanceof Error ? err.message : "Unknown error");
      } finally {
        setLoading(false);
      }
    }
    if (token) {
      void load();
    }
  }, [token]);

  return (
    <section className="space-y-4">
      <h2 className="text-xl font-semibold">Shared Folder View</h2>
      {loading ? <InlineNotice>Loading shared folder...</InlineNotice> : null}
      {error ? <InlineNotice tone="error">Error: {error}</InlineNotice> : null}
      {folder ? (
        <Card className="space-y-2">
          <p className="font-medium">{folder.name}</p>
          {folder.items.length === 0 ? <p>No items yet.</p> : null}
          <ul className="list-disc pl-5">
            {folder.items.map((item) => (
              <li key={item.folder_item_id}>
                {item.event_title} (score: {item.vote_score})
              </li>
            ))}
          </ul>
        </Card>
      ) : null}
    </section>
  );
}
