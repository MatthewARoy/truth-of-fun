"use client";

import { useState } from "react";
import Link from "next/link";
import type {
  ConciergeResponse,
  PortableItineraryResponse,
  TravelMode,
} from "@truth-of-fun/api-client";
import { PlanningInputs, placeInput, stopInputs, type StopDraft } from "@/components/planning-inputs";
import { apiClient } from "@/lib/api/client";
import { useAuth } from "@/lib/auth-context";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import { Card } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { InlineNotice } from "@/components/ui/inline-notice";
import { CopyButton } from "@/components/copy-button";
import { ItinerarySteps } from "@/components/itinerary-steps";
import { Select } from "@/components/ui/select";
import { formatLocalDay, formatLocalTime } from "@/lib/localtime";

const EXAMPLE_PROMPTS = [
  "I want to plan a date in the Mission for midday Saturday, followed by some activity, with an easy extension into an evening.",
  "Fun things to do with out-of-town guests this weekend, starting near the waterfront",
  "Bar crawl in Oakland on Friday night, starting around 8pm",
  "Chill Sunday afternoon — outdoor activities or a museum, then dinner",
  "High energy Saturday night — live music or a rave, anywhere in SF",
];

export default function PlannerPage() {
  const { ready, token } = useAuth();
  if (!ready) return <InlineNotice>Loading planner...</InlineNotice>;
  return <PlannerContent key={token ?? "anonymous"} />;
}

function PlannerContent() {
  const { token } = useAuth();
  const [query, setQuery] = useState("");
  const [expiresInDays, setExpiresInDays] = useState(14);
  const [origin, setOrigin] = useState({ name: "", lat: "", lng: "" });
  const [travelMode, setTravelMode] = useState<TravelMode>("driving");
  const [userStops, setUserStops] = useState<StopDraft[]>([]);
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
      const response = await apiClient.buildItinerary({ query: query.trim(), origin: placeInput(origin), travel_mode: travelMode, user_stops: stopInputs(userStops) });
      setResult(response);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to build itinerary");
    } finally {
      setLoading(false);
    }
  }

  async function handleShare() {
    if (!result || !token || shared || sharing) return;
    setSharing(true);
    setShareError(null);
    try {
      // Send the stops on screen rather than the prompt: re-planning server
      // side could hand back a different night than the one being shared.
      const response = await apiClient.shareItinerary({
        expires_in_days: expiresInDays,
        intent: result.intent,
        timeframe: result.timeframe,
        geography: result.geography,
        anchor_event_id: result.anchor_event_id,
        origin: result.origin,
        travel_mode: result.travel_mode,
        stops: result.itinerary.map((stop) => stop.provenance === "planner" ? ({
          kind: stop.kind,
          user_stop: { kind: stop.kind as "meeting" | "walk" | "activity", title: stop.title,
            place: { name: stop.venue_name, address: stop.address, lat: stop.lat, lng: stop.lng },
            start_at: stop.start_at, end_at: stop.end_at },
        }) : ({ kind: stop.kind, event_id: stop.event_id })),
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
        <PlanningInputs origin={origin} setOrigin={value => { setOrigin(value); resetResults(); }} mode={travelMode} setMode={value => { setTravelMode(value); resetResults(); }} stops={userStops} setStops={value => { setUserStops(value); resetResults(); }} disabled={loading || sharing} />
        <Button type="submit" disabled={loading || sharing || !query.trim()}>
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
              disabled={loading || sharing}
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
              {result.resolved_area ? <Badge>{result.resolved_area.label} · {result.resolved_area.radius_miles} mi radius</Badge> : result.geography && <Badge>{result.geography}</Badge>}
              <Badge>{result.travel_mode ?? "driving"}</Badge>
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
                    Copy the plan as text, or create a public link you can manage later.
                  </p>
                </div>

                <CopyButton value={result.text} label="Copy as text" />

                {token ? (
                  <>
                    <p className="text-sm text-slate-300">
                      Anyone with the link can read this plan, including your starting point and any stops you added, until it expires or you revoke it.
                      Your original request stays private and is not included in the link.
                    </p>
                    <Select
                      label="Public link expires after"
                      value={expiresInDays}
                      onChange={(event) => setExpiresInDays(Number(event.target.value))}
                      disabled={sharing || Boolean(shared)}
                    >
                      <option value={7}>7 days</option>
                      <option value={14}>14 days</option>
                      <option value={30}>30 days</option>
                    </Select>
                    <Button type="button" onClick={handleShare} disabled={sharing || Boolean(shared)}>
                      {sharing ? "Creating public link..." : shared ? "Public link created" : "Create public link"}
                    </Button>
                  </>
                ) : (
                  <InlineNotice tone="info">
                    Sign in to create a public link. You can copy this plan now.
                    Copy it before leaving this page to sign in; this draft is not saved.
                  </InlineNotice>
                )}

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
                    <p className="text-sm text-slate-400">
                      Expires {formatLocalDay(shared.expires_at)} at {formatLocalTime(shared.expires_at)} Pacific time.
                    </p>
                    <Link href="/shared-plans" className="text-sm text-brand-200 underline">
                      Manage or revoke shared plans
                    </Link>
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
