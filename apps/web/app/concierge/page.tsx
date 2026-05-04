"use client";

import { useState } from "react";
import type { ConciergeResponse } from "@truth-of-fun/api-client";
import { apiClient } from "@/lib/api/client";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { InlineNotice } from "@/components/ui/inline-notice";
import { Input } from "@/components/ui/input";

export default function ConciergePage() {
  const [query, setQuery] = useState("");
  const [result, setResult] = useState<ConciergeResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function submit() {
    setLoading(true);
    setError(null);
    try {
      const response = await apiClient.buildItinerary({ query, limit: 25 });
      setResult(response);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Unknown error");
    } finally {
      setLoading(false);
    }
  }

  return (
    <section className="space-y-4">
      <h2 className="text-xl font-semibold">Concierge Planner</h2>
      <Card className="space-y-3">
        <Input
          value={query}
          onChange={(event) => setQuery(event.target.value)}
          label="What should we plan?"
          placeholder="Plan a date night in Oakland this Saturday"
        />
        <Button type="button" onClick={() => void submit()} disabled={loading || !query.trim()}>
          {loading ? "Generating..." : "Generate itinerary"}
        </Button>
      </Card>
      {error ? <InlineNotice tone="error">Error: {error}</InlineNotice> : null}
      {result ? (
        <Card className="space-y-2">
          <p>Intent: {result.intent}</p>
          <p>Timeframe: {result.timeframe}</p>
          <p>Geography: {result.geography || "Not specified"}</p>
          {result.itinerary.length === 0 ? <p>No itinerary found.</p> : null}
          <ol className="list-decimal space-y-2 pl-5">
            {result.itinerary.map((stop) => (
              <li key={`${stop.kind}-${stop.event_id}`}>
                <span className="font-medium">{stop.title}</span> ({stop.kind}) at{" "}
                {new Date(stop.start_at).toLocaleString()} | Travel buffer:{" "}
                {stop.travel_buffer_minutes_before} minutes
              </li>
            ))}
          </ol>
        </Card>
      ) : null}
    </section>
  );
}
