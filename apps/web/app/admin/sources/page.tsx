"use client";

import { useEffect, useState } from "react";
import type { SourceHealthEntry } from "@truth-of-fun/api-client";
import { apiClient } from "@/lib/api/client";
import { Card } from "@/components/ui/card";
import { InlineNotice } from "@/components/ui/inline-notice";
import { cn } from "@/lib/cn";

const STATUS_CLASSES: Record<SourceHealthEntry["status"], string> = {
  healthy: "border-emerald-500/40 bg-emerald-500/10 text-emerald-200",
  degraded: "border-amber-500/40 bg-amber-500/10 text-amber-200",
  failing: "border-rose-500/40 bg-rose-500/10 text-rose-200",
  unknown: "border-slate-700 bg-slate-800/40 text-slate-400",
};

const STATUS_DOT: Record<SourceHealthEntry["status"], string> = {
  healthy: "bg-emerald-400",
  degraded: "bg-amber-400",
  failing: "bg-rose-400",
  unknown: "bg-slate-500",
};

const SOURCE_TIER: Record<string, 1 | 2 | 3> = {
  ticketmaster: 1,
  eventbrite: 1,
  meetup: 1,
  funcheap_sf: 2,
  "19hz": 2,
  luma: 2,
  dothebay: 2,
  sfstation: 2,
  minnesotastreet: 2,
  reddit: 3,
  eddies_list: 3,
};

function relativeTime(iso: string | null): string {
  if (!iso) return "never";
  const then = new Date(iso).getTime();
  const seconds = Math.round((Date.now() - then) / 1000);
  if (seconds < 60) return `${seconds}s ago`;
  if (seconds < 3600) return `${Math.round(seconds / 60)}m ago`;
  if (seconds < 86400) return `${Math.round(seconds / 3600)}h ago`;
  return `${Math.round(seconds / 86400)}d ago`;
}

export default function AdminSourcesPage() {
  const [sources, setSources] = useState<SourceHealthEntry[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [refreshedAt, setRefreshedAt] = useState<Date | null>(null);

  async function load() {
    setLoading(true);
    setError(null);
    try {
      const response = await apiClient.getSourceHealth();
      setSources(response.sources);
      setRefreshedAt(new Date());
    } catch (err) {
      setError(err instanceof Error ? err.message : "Unknown error");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    void load();
    const interval = setInterval(() => void load(), 30_000);
    return () => clearInterval(interval);
  }, []);

  const counts = sources.reduce(
    (acc, s) => {
      acc[s.status] = (acc[s.status] ?? 0) + 1;
      return acc;
    },
    {} as Record<SourceHealthEntry["status"], number>
  );

  const totalEvents = sources.reduce((sum, s) => sum + (s.last_event_count ?? 0), 0);

  return (
    <section className="space-y-6">
      <div className="space-y-1">
        <h2 className="text-xl font-semibold">Source Health</h2>
        <p className="text-sm text-slate-400">
          Live status of the {sources.length || "–"} ingestion sources. Worker reports per source on every
          6-hour cycle. A source flips to <span className="text-amber-300">degraded</span> after one zero-result
          run and <span className="text-rose-300">failing</span> after two.
        </p>
      </div>

      <div className="grid gap-3 sm:grid-cols-4">
        <Card className="space-y-1">
          <div className="text-xs uppercase tracking-wider text-slate-500">Healthy</div>
          <div className="text-2xl font-semibold text-emerald-300">{counts.healthy ?? 0}</div>
        </Card>
        <Card className="space-y-1">
          <div className="text-xs uppercase tracking-wider text-slate-500">Degraded</div>
          <div className="text-2xl font-semibold text-amber-300">{counts.degraded ?? 0}</div>
        </Card>
        <Card className="space-y-1">
          <div className="text-xs uppercase tracking-wider text-slate-500">Failing</div>
          <div className="text-2xl font-semibold text-rose-300">{counts.failing ?? 0}</div>
        </Card>
        <Card className="space-y-1">
          <div className="text-xs uppercase tracking-wider text-slate-500">Last cycle events</div>
          <div className="text-2xl font-semibold text-slate-100">{totalEvents.toLocaleString()}</div>
        </Card>
      </div>

      {error ? <InlineNotice tone="error">Error loading source health: {error}</InlineNotice> : null}

      {loading && sources.length === 0 ? (
        <InlineNotice>Loading source health...</InlineNotice>
      ) : sources.length === 0 ? (
        <InlineNotice>No sources registered.</InlineNotice>
      ) : (
        <Card padding="none" className="overflow-hidden">
          <table className="w-full text-sm">
            <thead className="border-b border-slate-800 bg-slate-900/60 text-left text-xs uppercase tracking-wider text-slate-400">
              <tr>
                <th className="px-4 py-3">Source</th>
                <th className="px-4 py-3">Tier</th>
                <th className="px-4 py-3">Status</th>
                <th className="px-4 py-3">Last events</th>
                <th className="px-4 py-3">Last run</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-800">
              {sources.map((s) => {
                const tier = SOURCE_TIER[s.name] ?? 3;
                return (
                  <tr key={s.name} className="hover:bg-slate-900/40">
                    <td className="px-4 py-3 font-medium text-slate-100">{s.name}</td>
                    <td className="px-4 py-3 text-slate-400">T{tier}</td>
                    <td className="px-4 py-3">
                      <span
                        className={cn(
                          "inline-flex items-center gap-2 rounded-full border px-2.5 py-1 text-xs font-medium",
                          STATUS_CLASSES[s.status]
                        )}
                      >
                        <span className={cn("h-1.5 w-1.5 rounded-full", STATUS_DOT[s.status])} />
                        {s.status}
                        {s.consecutive_zeros > 0 ? (
                          <span className="ml-1 opacity-75">({s.consecutive_zeros}× zero)</span>
                        ) : null}
                      </span>
                    </td>
                    <td className="px-4 py-3 text-slate-300">
                      {s.last_event_count == null ? "—" : s.last_event_count.toLocaleString()}
                    </td>
                    <td className="px-4 py-3 text-slate-400">{relativeTime(s.last_run_at)}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </Card>
      )}

      <p className="text-xs text-slate-500">
        Auto-refreshes every 30 seconds.
        {refreshedAt ? ` Last fetched ${refreshedAt.toLocaleTimeString()}.` : null}
      </p>
    </section>
  );
}
