"use client";

import { useState } from "react";
import type { ConciergeResponse } from "@truth-of-fun/api-client";
import { apiClient } from "@/lib/api/client";
import { useAuth } from "@/lib/auth-context";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import { Card } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { InlineNotice } from "@/components/ui/inline-notice";

const EXAMPLE_PROMPTS = [
  "I want to plan a date in the Mission for midday Saturday, followed by some activity, with an easy extension into an evening.",
  "Fun things to do with out-of-town guests this weekend, starting near the waterfront",
  "Bar crawl in Oakland on Friday night, starting around 8pm",
  "Chill Sunday afternoon — outdoor activities or a museum, then dinner",
  "High energy Saturday night — live music or a rave, anywhere in SF",
];

export default function PlannerPage() {
  const { token } = useAuth();
  const [query, setQuery] = useState("");
  const [loading, setLoading] = useState(false);
  const [result, setResult] = useState<ConciergeResponse | null>(null);
  const [error, setError] = useState<string | null>(null);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!query.trim()) return;

    setLoading(true);
    setError(null);
    setResult(null);
    try {
      const response = await apiClient.buildItinerary({ query: query.trim() });
      setResult(response);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to build itinerary");
    } finally {
      setLoading(false);
    }
  }

  function applyExamplePrompt(prompt: string) {
    setQuery(prompt);
    setResult(null);
    setError(null);
  }

  return (
    <div className="mx-auto max-w-2xl space-y-6">
      <div className="space-y-2">
        <h2 className="text-xl font-semibold">Plan Something</h2>
        <p className="text-sm text-slate-400">
          Describe what you want to do in plain English. We&apos;ll find events and build an itinerary for you.
        </p>
      </div>

      {!token && (
        <InlineNotice tone="info">
          Sign in to get personalized itineraries based on your preferences.
        </InlineNotice>
      )}

      <form onSubmit={handleSubmit} className="space-y-4">
        <Textarea
          placeholder="e.g. I want to plan a date in the Mission for Saturday afternoon..."
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          rows={3}
        />
        <Button type="submit" disabled={loading || !query.trim()}>
          {loading ? "Building your plan..." : "Build itinerary"}
        </Button>
      </form>

      {/* Example prompts */}
      <div className="space-y-2">
        <p className="text-xs text-slate-500 uppercase tracking-wider">Try an example</p>
        <div className="flex flex-wrap gap-2">
          {EXAMPLE_PROMPTS.map((prompt, i) => (
            <button
              key={i}
              type="button"
              onClick={() => applyExamplePrompt(prompt)}
              className="rounded-ui border border-slate-700 bg-slate-800/50 px-3 py-2 text-left text-xs text-slate-300 transition hover:border-slate-600 hover:bg-slate-800"
            >
              {prompt.length > 60 ? prompt.slice(0, 60) + "..." : prompt}
            </button>
          ))}
        </div>
      </div>

      {error && <InlineNotice tone="error">{error}</InlineNotice>}

      {/* Itinerary result */}
      {result && (
        <div className="space-y-4">
          <Card className="space-y-3">
            <h3 className="text-lg font-semibold">Your Plan</h3>
            <div className="flex flex-wrap gap-2">
              {result.intent && <Badge active>{result.intent.replace(/_/g, " ")}</Badge>}
              {result.timeframe && <Badge>{result.timeframe}</Badge>}
              {result.geography && <Badge>{result.geography}</Badge>}
            </div>
          </Card>

          {result.itinerary.length === 0 ? (
            <InlineNotice>
              No events found matching your plan. Try broadening the area or timeframe.
            </InlineNotice>
          ) : (
            <div className="relative space-y-0">
              {result.itinerary.map((stop, idx) => (
                <div key={idx} className="relative flex gap-4 pb-6">
                  {/* Timeline line */}
                  <div className="flex flex-col items-center">
                    <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-brand-500 text-sm font-bold text-white">
                      {idx + 1}
                    </div>
                    {idx < result.itinerary.length - 1 && (
                      <div className="w-px flex-1 bg-slate-700" />
                    )}
                  </div>

                  {/* Stop card */}
                  <Card className="flex-1 space-y-2">
                    <div className="flex items-start justify-between gap-2">
                      <div>
                        <h4 className="font-semibold">{stop.title}</h4>
                        <p className="text-sm text-slate-400">
                          {stop.venue_name || "Venue TBD"}
                        </p>
                      </div>
                      <Badge active>{stop.kind.replace(/_/g, " ")}</Badge>
                    </div>

                    <p className="text-sm text-slate-300">
                      {new Date(stop.start_at).toLocaleString(undefined, {
                        weekday: "short",
                        month: "short",
                        day: "numeric",
                        hour: "numeric",
                        minute: "2-digit",
                      })}
                      {stop.end_at && (
                        <> &mdash; {new Date(stop.end_at).toLocaleTimeString(undefined, { hour: "numeric", minute: "2-digit" })}</>
                      )}
                    </p>

                    {stop.travel_buffer_minutes_before > 0 && (
                      <p className="text-xs text-slate-500">
                        {stop.travel_buffer_minutes_before} min travel time before
                      </p>
                    )}

                    {stop.external_url && (
                      <a
                        href={stop.external_url}
                        target="_blank"
                        rel="noreferrer"
                        className="inline-block rounded-ui bg-emerald-800 px-3 py-1.5 text-xs text-emerald-100 transition hover:bg-emerald-700"
                      >
                        View / Get tickets
                      </a>
                    )}
                  </Card>
                </div>
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  );
}
