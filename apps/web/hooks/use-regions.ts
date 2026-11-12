"use client";

import { useEffect, useState } from "react";
import type { Region } from "@truth-of-fun/api-client";
import { apiClient } from "@/lib/api/client";
import { FALLBACK_REGIONS, REGION_IDS } from "@/lib/explore-params";

export type RegionOption = Pick<Region, "id" | "label"> & {
  /** Null when counts are unavailable (the fallback list). */
  upcomingCount: number | null;
  cities: Region["cities"];
};

const FALLBACK: RegionOption[] = FALLBACK_REGIONS.map((region) => ({
  ...region, upcomingCount: null, cities: [],
}));

/**
 * The five regions with their cities and counts. The region chips must work
 * even when GET /regions does not, so the static list is shown immediately and
 * simply stays if the request fails — the filter itself only needs the id.
 */
export function useRegions(): { regions: RegionOption[]; live: boolean } {
  const [state, setState] = useState<{ regions: RegionOption[]; live: boolean }>({
    regions: FALLBACK, live: false,
  });

  useEffect(() => {
    const controller = new AbortController();
    apiClient.getRegions({ signal: controller.signal })
      .then((response) => {
        if (controller.signal.aborted) return;
        const regions = (Array.isArray(response?.regions) ? response.regions : [])
          .filter((region) => REGION_IDS.includes(region.id) && typeof region.label === "string")
          .map((region) => ({
            id: region.id,
            label: region.label,
            upcomingCount: typeof region.upcoming_count === "number" ? region.upcoming_count : null,
            cities: Array.isArray(region.cities)
              ? region.cities.filter((city) => typeof city?.name === "string" && city.name)
              : [],
          }));
        if (regions.length > 0) setState({ regions, live: true });
      })
      .catch(() => {
        // Keep the static list; filtering by region still works without counts.
      });
    return () => controller.abort();
  }, []);

  return state;
}
