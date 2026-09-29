"use client";

import { useCallback, useState } from "react";
import type { RecommendationResponse } from "@truth-of-fun/api-client";
import { apiClient } from "@/lib/api/client";

export function useRecommendations() {
  const [items, setItems] = useState<RecommendationResponse[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const loadRecommendations = useCallback(async (signal?: AbortSignal) => {
    setLoading(true);
    setError(null);
    try {
      const result = await apiClient.getRecommendations(25, 0, { signal });
      if (signal?.aborted) return;
      setItems(result);
    } catch (err) {
      if (signal?.aborted) return;
      setError(err instanceof Error ? err.message : "Unknown error");
    } finally {
      if (!signal?.aborted) setLoading(false);
    }
  }, []);

  return { items, loading, error, loadRecommendations };
}
