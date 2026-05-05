"use client";

import { useEffect, useMemo, useRef } from "react";
import type { EventResponse } from "@truth-of-fun/api-client";

type Props = {
  events: EventResponse[];
  selectedId?: number | null;
  onSelect?: (eventId: number | null) => void;
};

const SF_CENTER: [number, number] = [37.7749, -122.4194];

export function EventMap({ events, selectedId, onSelect }: Props) {
  const containerRef = useRef<HTMLDivElement>(null);
  const mapRef = useRef<unknown>(null);
  const markersRef = useRef<Map<number, unknown>>(new Map());

  const points = useMemo(
    () => events.filter((e) => typeof e.lat === "number" && typeof e.lng === "number"),
    [events]
  );

  useEffect(() => {
    let cancelled = false;
    let resizeObserver: ResizeObserver | null = null;

    async function init() {
      if (!containerRef.current) return;
      // Load Leaflet client-side only (it touches `window`).
      // CSS is imported in globals.css.
      const L = (await import("leaflet")).default;
      if (cancelled || !containerRef.current) return;

      if (mapRef.current) {
        return;
      }

      const map = L.map(containerRef.current, {
        center: SF_CENTER,
        zoom: 12,
        zoomControl: true,
        attributionControl: true,
      });

      L.tileLayer(
        "https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png",
        {
          attribution:
            '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> &copy; <a href="https://carto.com/attributions">CARTO</a>',
          subdomains: "abcd",
          maxZoom: 19,
        }
      ).addTo(map);

      mapRef.current = map as unknown;

      // ResizeObserver: Leaflet needs invalidateSize when its container resizes
      // (e.g., when the parent grid changes columns).
      resizeObserver = new ResizeObserver(() => {
        (map as { invalidateSize: () => void }).invalidateSize();
      });
      resizeObserver.observe(containerRef.current);

      renderMarkers(L, map);
    }

    function renderMarkers(L: typeof import("leaflet"), map: unknown) {
      // Clear existing
      markersRef.current.forEach((marker) => {
        (marker as { remove: () => void }).remove();
      });
      markersRef.current.clear();

      const bounds: Array<[number, number]> = [];
      for (const event of points) {
        if (event.lat == null || event.lng == null) continue;
        const isSelected = event.id === selectedId;
        const icon = L.divIcon({
          className: "tof-marker",
          html: `<div class="tof-marker-pin ${
            isSelected ? "tof-marker-pin--selected" : ""
          }">${isSelected ? "★" : "•"}</div>`,
          iconSize: [28, 28],
          iconAnchor: [14, 14],
        });
        const marker = L.marker([event.lat, event.lng], { icon })
          .addTo(map as L.Map)
          .bindPopup(
            `<div class="tof-popup">
              <strong>${escapeHtml(event.title)}</strong><br/>
              <span>${escapeHtml(event.venue_name ?? "Venue TBD")}</span>
            </div>`
          )
          .on("click", () => {
            onSelect?.(event.id);
          });
        markersRef.current.set(event.id, marker);
        bounds.push([event.lat, event.lng]);
      }

      if (bounds.length > 0) {
        (map as L.Map).fitBounds(bounds as [number, number][], {
          padding: [40, 40],
          maxZoom: 14,
        });
      }
    }

    void init();

    const markers = markersRef;
    return () => {
      cancelled = true;
      resizeObserver?.disconnect();
      if (mapRef.current) {
        (mapRef.current as { remove: () => void }).remove();
        mapRef.current = null;
        markers.current.clear();
      }
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Re-render markers when events or selection change
  useEffect(() => {
    if (!mapRef.current) return;
    let cancelled = false;
    (async () => {
      const L = (await import("leaflet")).default;
      if (cancelled || !mapRef.current) return;
      const map = mapRef.current;

      markersRef.current.forEach((marker) => {
        (marker as { remove: () => void }).remove();
      });
      markersRef.current.clear();

      const bounds: Array<[number, number]> = [];
      for (const event of points) {
        if (event.lat == null || event.lng == null) continue;
        const isSelected = event.id === selectedId;
        const icon = L.divIcon({
          className: "tof-marker",
          html: `<div class="tof-marker-pin ${
            isSelected ? "tof-marker-pin--selected" : ""
          }">${isSelected ? "★" : "•"}</div>`,
          iconSize: [28, 28],
          iconAnchor: [14, 14],
        });
        const marker = L.marker([event.lat, event.lng], { icon })
          .addTo(map as L.Map)
          .bindPopup(
            `<div class="tof-popup">
              <strong>${escapeHtml(event.title)}</strong><br/>
              <span>${escapeHtml(event.venue_name ?? "Venue TBD")}</span>
            </div>`
          )
          .on("click", () => {
            onSelect?.(event.id);
          });
        markersRef.current.set(event.id, marker);
        bounds.push([event.lat, event.lng]);
      }

      if (bounds.length > 0 && selectedId == null) {
        (map as L.Map).fitBounds(bounds as [number, number][], {
          padding: [40, 40],
          maxZoom: 14,
        });
      } else if (selectedId != null) {
        const selected = points.find((e) => e.id === selectedId);
        if (selected && selected.lat != null && selected.lng != null) {
          (map as L.Map).setView([selected.lat, selected.lng], 15, { animate: true });
          const marker = markersRef.current.get(selectedId) as
            | { openPopup?: () => void }
            | undefined;
          marker?.openPopup?.();
        }
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [points, selectedId, onSelect]);

  if (points.length === 0) {
    return (
      <div className="flex h-[480px] items-center justify-center rounded-ui border border-slate-800 bg-slate-900 text-sm text-slate-400">
        No mappable events. Try adjusting filters.
      </div>
    );
  }

  return (
    <div
      ref={containerRef}
      className="h-[480px] w-full overflow-hidden rounded-ui border border-slate-800"
      role="application"
      aria-label="Event venue map"
    />
  );
}

function escapeHtml(s: string): string {
  return s
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#39;");
}
