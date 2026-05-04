"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { useAuth } from "@/lib/auth-context";
import { apiClient } from "@/lib/api/client";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Card } from "@/components/ui/card";
import { InlineNotice } from "@/components/ui/inline-notice";

const VIBE_OPTIONS = [
  { tag: "#LiveMusic", label: "Live Music", emoji: "🎵" },
  { tag: "#Comedy", label: "Comedy", emoji: "😂" },
  { tag: "#Nightlife", label: "Nightlife & Clubs", emoji: "🌃" },
  { tag: "#FoodAndDrink", label: "Food & Drink", emoji: "🍷" },
  { tag: "#Outdoors", label: "Outdoors & Nature", emoji: "🌲" },
  { tag: "#Tech", label: "Tech & Startups", emoji: "💻" },
  { tag: "#Art", label: "Art & Museums", emoji: "🎨" },
  { tag: "#Sports", label: "Sports", emoji: "⚽" },
  { tag: "#Theater", label: "Theater & Film", emoji: "🎭" },
  { tag: "#Wellness", label: "Wellness & Fitness", emoji: "🧘" },
  { tag: "#Family", label: "Family Friendly", emoji: "👨‍👩‍👧" },
  { tag: "#Free", label: "Free Events", emoji: "🆓" },
  { tag: "#Social", label: "Mixers & Networking", emoji: "🤝" },
  { tag: "#HighEnergy", label: "Raves & Festivals", emoji: "🔥" },
  { tag: "#Chill", label: "Chill & Relaxed", emoji: "☕" },
  { tag: "#Intellectual", label: "Talks & Lectures", emoji: "📚" },
];

type Mode = "login" | "signup";
type Step = "credentials" | "vibes";

export default function LoginPage() {
  const router = useRouter();
  const { login, register } = useAuth();
  const [mode, setMode] = useState<Mode>("signup");
  const [step, setStep] = useState<Step>("credentials");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [selectedVibes, setSelectedVibes] = useState<Set<string>>(new Set());
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  function toggleVibe(tag: string) {
    setSelectedVibes((prev) => {
      const next = new Set(prev);
      if (next.has(tag)) next.delete(tag);
      else next.add(tag);
      return next;
    });
  }

  async function handleCredentials(e: React.FormEvent) {
    e.preventDefault();
    setLoading(true);
    setError(null);
    try {
      if (mode === "signup") {
        await register(email, password);
        setStep("vibes");
      } else {
        await login(email, password);
        router.push("/explore");
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : "Authentication failed");
    } finally {
      setLoading(false);
    }
  }

  async function handleVibesComplete() {
    setLoading(true);
    setError(null);
    try {
      if (selectedVibes.size > 0) {
        // Send vibes as an onboarding description
        const vibeLabels = [...selectedVibes].map((tag) => {
          const opt = VIBE_OPTIONS.find((v) => v.tag === tag);
          return opt?.label ?? tag;
        });
        await apiClient.submitOnboarding({
          perfect_saturday: `I enjoy ${vibeLabels.join(", ")}`,
        });
      }
      router.push("/explore");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to save preferences");
    } finally {
      setLoading(false);
    }
  }

  if (step === "vibes") {
    return (
      <div className="mx-auto max-w-xl space-y-6">
        <div className="space-y-2">
          <h2 className="text-xl font-semibold">What are you into?</h2>
          <p className="text-sm text-slate-400">Pick a few categories so we can personalize your feed. You can always change these later.</p>
        </div>

        <div className="flex flex-wrap gap-2">
          {VIBE_OPTIONS.map((opt) => {
            const active = selectedVibes.has(opt.tag);
            return (
              <button
                key={opt.tag}
                type="button"
                onClick={() => toggleVibe(opt.tag)}
                className={
                  active
                    ? "rounded-full border border-brand-400 bg-brand-500/20 px-4 py-2 text-sm text-brand-100 transition hover:bg-brand-500/30"
                    : "rounded-full border border-slate-700 bg-slate-800/50 px-4 py-2 text-sm text-slate-300 transition hover:border-slate-600 hover:bg-slate-800"
                }
              >
                {opt.emoji} {opt.label}
              </button>
            );
          })}
        </div>

        {selectedVibes.size > 0 && (
          <p className="text-sm text-slate-400">
            Selected: {[...selectedVibes].map((t) => VIBE_OPTIONS.find((v) => v.tag === t)?.label).join(", ")}
          </p>
        )}

        {error && <InlineNotice tone="error">{error}</InlineNotice>}

        <div className="flex gap-3">
          <Button onClick={handleVibesComplete} disabled={loading}>
            {loading ? "Saving..." : selectedVibes.size > 0 ? "Continue" : "Skip for now"}
          </Button>
        </div>
      </div>
    );
  }

  return (
    <div className="mx-auto max-w-sm space-y-6">
      <Card className="space-y-5">
        <div className="space-y-1">
          <h2 className="text-xl font-semibold">{mode === "signup" ? "Create account" : "Welcome back"}</h2>
          <p className="text-sm text-slate-400">
            {mode === "signup" ? "Sign up to save events and get personalized recommendations" : "Sign in to your account"}
          </p>
        </div>

        <form onSubmit={handleCredentials} className="space-y-4">
          <Input
            label="Email"
            type="email"
            placeholder="you@example.com"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            required
          />
          <Input
            label="Password"
            type="password"
            placeholder="Min 6 characters"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            required
            minLength={6}
          />
          {error && <InlineNotice tone="error">{error}</InlineNotice>}
          <Button type="submit" fullWidth disabled={loading}>
            {loading ? "Loading..." : mode === "signup" ? "Create account" : "Sign in"}
          </Button>
        </form>

        <p className="text-center text-sm text-slate-400">
          {mode === "signup" ? "Already have an account?" : "Don't have an account?"}{" "}
          <button
            type="button"
            onClick={() => { setMode(mode === "signup" ? "login" : "signup"); setError(null); }}
            className="text-brand-300 hover:text-brand-200 transition"
          >
            {mode === "signup" ? "Sign in" : "Sign up"}
          </button>
        </p>
      </Card>
    </div>
  );
}
