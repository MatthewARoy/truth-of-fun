"use client";

import type { ItineraryStopResponse, StopLinks } from "@truth-of-fun/api-client";
import { cn } from "@/lib/cn";
import { formatLocalDay, formatLocalTime } from "@/lib/localtime";

const STOP_KIND_LABELS: Record<string, string> = {
  pre_event_drink: "Before",
  main_event: "Main event",
  late_night_snack: "After",
};

function stopKindLabel(kind: string): string {
  return STOP_KIND_LABELS[kind] ?? kind.replace(/_/g, " ");
}

function formatTimeRange(startAt: string, endAt: string | null): string {
  return endAt
    ? `${formatLocalTime(startAt)} – ${formatLocalTime(endAt)}`
    : formatLocalTime(startAt);
}

/** Ordered so the two things you need while driving come first. */
const LINK_CHIPS: { key: keyof StopLinks; label: string; primary?: boolean }[] = [
  { key: "directions_url", label: "Directions", primary: true },
  { key: "parking_url", label: "Parking" },
  { key: "food_url", label: "Food nearby" },
  { key: "drinks_url", label: "Drinks nearby" },
  { key: "tickets_url", label: "Tickets", primary: true },
];

function LinkChips({ links }: { links: StopLinks }) {
  const available = LINK_CHIPS.filter((chip) => links[chip.key]);
  if (available.length === 0) return null;

  return (
    <div className="flex flex-wrap gap-2 pt-1">
      {available.map((chip) => (
        <a
          key={chip.key}
          href={links[chip.key] as string}
          target="_blank"
          rel="noreferrer"
          // min-h-11 keeps every chip at a thumb-sized tap target on a phone.
          className={cn(
            "inline-flex min-h-11 items-center rounded-ui px-3 text-sm font-medium transition",
            chip.primary
              ? "bg-brand-500 text-white hover:bg-brand-400"
              : "border border-slate-700 bg-slate-800 text-slate-200 hover:bg-slate-700"
          )}
        >
          {chip.label}
        </a>
      ))}
    </div>
  );
}

type Props = {
  stops: ItineraryStopResponse[];
  /** Repeat the date on every stop — set when a plan can span past midnight. */
  showDayPerStop?: boolean;
};

export function ItinerarySteps({ stops, showDayPerStop = false }: Props) {
  return (
    <ol className="space-y-3">
      {stops.map((stop, index) => (
        <li key={`${stop.event_id}-${index}`} className="space-y-2">
          {stop.travel_buffer_minutes_before > 0 && index > 0 && (
            <p className="pl-11 text-xs text-slate-500">
              ↓ leave ~{stop.travel_buffer_minutes_before} min ahead
            </p>
          )}

          <div className="rounded-ui border border-slate-800 bg-slate-900 p-4">
            <div className="flex gap-3">
              <span
                aria-hidden
                className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-brand-500 text-sm font-bold text-white"
              >
                {index + 1}
              </span>

              <div className="min-w-0 flex-1 space-y-1">
                <div className="flex flex-wrap items-baseline gap-x-2 gap-y-1">
                  <span className="text-base font-semibold text-brand-100">
                    {formatTimeRange(stop.start_at, stop.end_at)}
                  </span>
                  {showDayPerStop && (
                    <span className="text-xs text-slate-500">
                      {formatLocalDay(stop.start_at)}
                    </span>
                  )}
                  <span className="text-xs uppercase tracking-wide text-slate-500">
                    {stopKindLabel(stop.kind)}
                  </span>
                </div>

                {/* break-words: scraped titles run long and must not scroll the page sideways. */}
                <h3 className="break-words font-semibold leading-snug">{stop.title}</h3>

                {(stop.venue_name || stop.address) && (
                  <p className="break-words text-sm text-slate-400">
                    {stop.venue_name}
                    {stop.venue_name && stop.address && " · "}
                    {stop.address}
                  </p>
                )}
              </div>
            </div>

            <LinkChips links={stop.links} />
          </div>
        </li>
      ))}
    </ol>
  );
}
