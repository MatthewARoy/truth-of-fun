"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import type { EventResponse } from "@truth-of-fun/api-client";
import { eventStartLabel, hasVenuePin, statusNotice } from "@/lib/event-format";

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
  const [mapReady, setMapReady] = useState(false);

  // Low-confidence coordinates are a source's city-centre fallback. Plotting
  // them would stack dozens of unrelated events on one pin in the middle of
  // town and claim a venue location nobody published, so they stay off the
  // map and the reader is told how many were left out.
  const points = useMemo(() => events.filter(hasVenuePin), [events]);
  const hiddenCount = useMemo(
    () => events.filter(
      (e) => typeof e.lat === "number" && typeof e.lng === "number" && !hasVenuePin(e)
    ).length,
    [events]
  );
  const unlocatedCount = events.length - points.length - hiddenCount;

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

      // Marker rendering happens in the effect below once the map is ready.
      setMapReady(true);
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
      setMapReady(false);
    };
  }, []);

  // Render markers once the map is ready, and re-render when events or selection change
  useEffect(() => {
    if (!mapReady || !mapRef.current) return;
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
          .bindPopup(popupHtml(event))
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
  }, [mapReady, points, selectedId, onSelect]);

  // The map container always renders so the Leaflet instance survives filter
  // changes; an overlay communicates the empty state instead of unmounting it.
  const notes: string[] = [];
  if (hiddenCount > 0) {
    notes.push(
      `${hiddenCount.toLocaleString()} ${hiddenCount === 1 ? "event is" : "events are"} not shown on the map because `
      + `${hiddenCount === 1 ? "its" : "their"} location is only approximate.`
    );
  }
  if (unlocatedCount > 0) {
    notes.push(
      `${unlocatedCount.toLocaleString()} ${unlocatedCount === 1 ? "event has" : "events have"} no location to plot.`
    );
  }

  return (
    <div className="space-y-2">
      <div className="relative h-[480px] w-full overflow-hidden rounded-ui border border-slate-800">
        <div
          ref={containerRef}
          className="h-full w-full"
          role="application"
          aria-label="Event venue map"
        />
        {points.length === 0 ? (
          <div className="absolute inset-0 z-[1000] flex items-center justify-center bg-slate-950/80 px-4 text-center text-sm text-slate-400">
            No mappable events. Try adjusting filters.
          </div>
        ) : null}
      </div>
      {events.length > 0 ? (
        <p className="text-xs text-slate-400" data-testid="map-summary">
          Showing {points.length.toLocaleString()} of {events.length.toLocaleString()} loaded events on the map.
          {notes.length > 0 ? ` ${notes.join(" ")} Switch to the list to see them.` : ""}
        </p>
      ) : null}
    </div>
  );
}

// Leaflet popups are HTML strings, so every value from the API is escaped and
// the only link is a same-site path built from the numeric id.
function popupHtml(event: EventResponse): string {
  const notice = statusNotice(event.status);
  const when = `${notice ? `${notice.label} · originally ` : ""}${eventStartLabel(event)}`;
  const place = [event.venue_name ?? "Venue TBD", event.city].filter(Boolean).join(" · ");
  return `<div class="tof-popup">
    <strong>${escapeHtml(event.title)}</strong><br/>
    <span>${escapeHtml(when)}</span><br/>
    <span>${escapeHtml(place)}</span><br/>
    <a href="/events/${encodeURIComponent(String(event.id))}">View event details</a>
  </div>`;
}

function escapeHtml(s: string): string {
  return s
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#39;");
}
