"use client";

import { useState } from "react";
import type {
  ConciergeResponse,
  PortableItineraryResponse,
} from "@truth-of-fun/api-client";
import { apiClient } from "@/lib/api/client";
import { useAuth } from "@/lib/auth-context";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import { Card } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { InlineNotice } from "@/components/ui/inline-notice";
import { CopyButton } from "@/components/copy-button";
import { ItinerarySteps } from "@/components/itinerary-steps";

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
  const [shared, setShared] = useState<PortableItineraryResponse | null>(null);
  const [sharing, setSharing] = useState(false);
  const [shareError, setShareError] = useState<string | null>(null);

  function resetResults() {
    setResult(null);
    setShared(null);
    setError(null);
    setShareError(null);
  }

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!query.trim()) return;

    setLoading(true);
    resetResults();
    try {
      const response = await apiClient.buildItinerary({ query: query.trim() });
      setResult(response);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to build itinerary");
    } finally {
      setLoading(false);
    }
  }

  async function handleShare() {
    if (!result) return;
    setSharing(true);
    setShareError(null);
    try {
      // Send the stops on screen rather than the prompt: re-planning server
      // side could hand back a different night than the one being shared.
      const response = await apiClient.shareItinerary({
        query: query.trim(),
        intent: result.intent,
        timeframe: result.timeframe,
        geography: result.geography,
        anchor_event_id: result.anchor_event_id,
        stops: result.itinerary.map((stop) => ({
          kind: stop.kind,
          event_id: stop.event_id,
          travel_buffer_minutes_before: stop.travel_buffer_minutes_before,
        })),
      });
      setShared(response);
    } catch (err) {
      setShareError(err instanceof Error ? err.message : "Failed to create share link");
    } finally {
      setSharing(false);
    }
  }

  function applyExamplePrompt(prompt: string) {
    setQuery(prompt);
    resetResults();
  }

  const shareLink =
    shared && typeof window !== "undefined"
      ? `${window.location.origin}${shared.share_url}`
      : shared?.share_url ?? "";

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
            <h3 className="text-lg font-semibold">{result.title || "Your Plan"}</h3>
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
            <>
              <ItinerarySteps stops={result.itinerary} />

              {/* Take it with you */}
              <Card className="space-y-3">
                <div>
                  <h3 className="font-semibold">Take it with you</h3>
                  <p className="text-sm text-slate-400">
                    A link that opens on any phone, or the whole plan as text you can
                    paste into a message.
                  </p>
                </div>

                <div className="flex flex-wrap gap-2">
                  <Button type="button" onClick={handleShare} disabled={sharing}>
                    {sharing ? "Creating link..." : shared ? "Link created" : "Get shareable link"}
                  </Button>
                  <CopyButton value={result.text} label="Copy as text" />
                </div>

                {shareError && <InlineNotice tone="error">{shareError}</InlineNotice>}

                {shared && (
                  <div className="space-y-2">
                    <a
                      href={shared.share_url}
                      target="_blank"
                      rel="noreferrer"
                      className="block break-all rounded-ui border border-slate-700 bg-slate-950 px-3 py-2 font-mono text-xs text-brand-200"
                    >
                      {shareLink}
                    </a>
                    <CopyButton value={shareLink} label="Copy link" />
                  </div>
                )}
              </Card>
            </>
          )}

        </div>
      )}
    </div>
  );
}
