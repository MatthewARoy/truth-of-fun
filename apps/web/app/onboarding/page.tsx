"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { apiClient } from "@/lib/api/client";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { InlineNotice } from "@/components/ui/inline-notice";
import { Textarea } from "@/components/ui/textarea";

export default function OnboardingPage() {
  const router = useRouter();
  const [prompt, setPrompt] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<string[]>([]);

  async function submit() {
    setLoading(true);
    setError(null);
    try {
      const response = await apiClient.submitOnboarding({ perfect_saturday: prompt });
      setResult(response.extracted_vibes);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Unknown error");
    } finally {
      setLoading(false);
    }
  }

  return (
    <section className="space-y-4">
      <h2 className="text-xl font-semibold">Onboarding</h2>
      <Card className="space-y-4">
        <p className="text-sm text-slate-300">
          Tell us what your ideal day looks like. We use this to tune recommendations immediately.
        </p>
        <Textarea
          className="min-h-40"
          value={prompt}
          onChange={(event) => setPrompt(event.target.value)}
          label="Describe your perfect Saturday"
          hint="One short paragraph is enough."
          placeholder="Brunch with friends, then an outdoor market, then live music at night."
        />
        <div className="flex flex-wrap gap-2">
          <Button type="button" onClick={() => void submit()} disabled={loading || !prompt.trim()}>
            {loading ? "Saving..." : "Save preferences"}
          </Button>
          <Button type="button" variant="ghost" onClick={() => router.push("/explore")}>
            Skip for now
          </Button>
        </div>
      </Card>
      {error ? <InlineNotice tone="error">Error: {error}</InlineNotice> : null}
      {result.length > 0 ? (
        <Card className="space-y-3">
          <h3 className="text-base font-semibold">We tuned recommendations for:</h3>
          <p className="text-sm text-brand-200">{result.join(", ")}</p>
          <div className="flex flex-wrap gap-2">
            <Button type="button" onClick={() => router.push("/recommendations")}>
              View recommendations
            </Button>
            <Button type="button" variant="secondary" onClick={() => setResult([])}>
              Edit response
            </Button>
          </div>
        </Card>
      ) : null}
    </section>
  );
}
