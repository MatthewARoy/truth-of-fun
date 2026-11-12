"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { useAuth } from "@/lib/auth-context";
import { apiClient } from "@/lib/api/client";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Card } from "@/components/ui/card";
import { InlineNotice } from "@/components/ui/inline-notice";
import { Chip } from "@/components/ui/chip";
import { safeReturnPath } from "@/lib/return-path";
import { VIBE_OPTIONS, vibeLabel } from "@/lib/vibes";

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
  const [sessionExpired, setSessionExpired] = useState(false);

  // Sent here because the API rejected the stored session: explain why, and
  // offer sign-in rather than the default sign-up form.
  useEffect(() => {
    if (new URLSearchParams(window.location.search).get("reason") === "expired") {
      setSessionExpired(true);
      setMode("login");
    }
  }, []);

  function finishLogin() {
    const next = new URLSearchParams(window.location.search).get("next");
    router.replace(safeReturnPath(next));
  }

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
        finishLogin();
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
      await apiClient.setPreferences({ preferred_vibes: [...selectedVibes] });
      finishLogin();
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
          <h1 className="text-xl font-semibold">What are you into?</h1>
          <p className="text-sm text-slate-400">
            Pick a few categories so we can personalize your feed. You can change these any time on
            your account page.
          </p>
        </div>

        <div className="flex flex-wrap gap-2" role="group" aria-label="Interests">
          {VIBE_OPTIONS.map((opt) => {
            const active = selectedVibes.has(opt.tag);
            return (
              <Chip key={opt.tag} size="md" pressed={active} onClick={() => toggleVibe(opt.tag)}>
                <span aria-hidden="true">{opt.emoji}</span> {opt.label}
              </Chip>
            );
          })}
        </div>

        {selectedVibes.size > 0 && (
          <p className="text-sm text-slate-400">
            Selected: {[...selectedVibes].map(vibeLabel).join(", ")}
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
          <h1 className="text-xl font-semibold">{mode === "signup" ? "Create account" : "Welcome back"}</h1>
          <p className="text-sm text-slate-400">
            {mode === "signup" ? "Sign up to save events and get personalized recommendations" : "Sign in to your account"}
          </p>
        </div>

        {sessionExpired ? (
          <InlineNotice tone="warning" role="status">
            Your session has ended. Sign in again to pick up where you left off.
          </InlineNotice>
        ) : null}

        <form onSubmit={handleCredentials} className="space-y-4">
          <Input
            label="Email"
            type="email"
            name="email"
            autoComplete="email"
            inputMode="email"
            autoCapitalize="none"
            spellCheck={false}
            placeholder="you@example.com"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            required
          />
          <Input
            label="Password"
            type="password"
            name="password"
            autoComplete={mode === "signup" ? "new-password" : "current-password"}
            hint={mode === "signup" ? "At least 12 characters." : undefined}
            placeholder={mode === "signup" ? "Min 12 characters" : "Your password"}
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            required
            minLength={mode === "signup" ? 12 : 1}
            maxLength={72}
          />
          {error && <InlineNotice tone="error">{error}</InlineNotice>}
          <Button type="submit" fullWidth disabled={loading}>
            {loading ? "Loading..." : mode === "signup" ? "Create account" : "Sign in"}
          </Button>
          {mode === "login" ? (
            <p className="text-center text-sm">
              <Link href="/forgot-password">Forgot password?</Link>
            </p>
          ) : (
            <p className="text-center text-xs text-slate-400">
              By creating an account you agree to the <Link href="/terms">Terms</Link> and{" "}
              <Link href="/privacy">Privacy Policy</Link>.
            </p>
          )}
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
