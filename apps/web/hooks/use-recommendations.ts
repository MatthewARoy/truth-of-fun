"use client";

import { useCallback, useState } from "react";
import type { RecommendationResponse } from "@truth-of-fun/api-client";
import { apiClient } from "@/lib/api/client";

export function useRecommendations() {
  const [items, setItems] = useState<RecommendationResponse[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const loadRecommendations = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const result = await apiClient.getRecommendations();
      setItems(result);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Unknown error");
    } finally {
      setLoading(false);
    }
  }, []);

  return { items, loading, error, loadRecommendations };
}
