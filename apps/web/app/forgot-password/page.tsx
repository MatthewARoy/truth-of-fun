"use client";

import Link from "next/link";
import { useState } from "react";
import { apiClient } from "@/lib/api/client";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { InlineNotice } from "@/components/ui/inline-notice";
import { Input } from "@/components/ui/input";

export default function ForgotPasswordPage() {
  const [email, setEmail] = useState("");
  const [loading, setLoading] = useState(false);
  const [sent, setSent] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setLoading(true);
    setError(null);
    try {
      await apiClient.requestPasswordReset(email.trim());
      setSent(true);
    } catch (err) {
      // Only transport or validation problems land here: the API answers the
      // same way whether or not the address has an account.
      setError(err instanceof Error ? err.message : "Could not send the request. Please try again.");
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="mx-auto max-w-sm space-y-6">
      <Card className="space-y-5">
        <div className="space-y-1">
          <h1 className="text-xl font-semibold">Reset your password</h1>
          <p className="text-sm text-slate-400">
            Enter the email address you signed up with and we&apos;ll send a link to choose a new
            password.
          </p>
        </div>

        {sent ? (
          <div className="space-y-4">
            {/* Deliberately identical for every address, so this form cannot
                be used to find out who has an account. */}
            <InlineNotice tone="success">
              If an account exists for that email address, a password reset link is on its way. It can
              take a few minutes to arrive, so check your spam folder too.
            </InlineNotice>
            <Button type="button" variant="secondary" fullWidth onClick={() => setSent(false)}>
              Use a different email address
            </Button>
          </div>
        ) : (
          <form onSubmit={handleSubmit} className="space-y-4">
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
            {error ? <InlineNotice tone="error">{error}</InlineNotice> : null}
            <Button type="submit" fullWidth disabled={loading}>
              {loading ? "Sending..." : "Send reset link"}
            </Button>
          </form>
        )}

        <p className="text-center text-sm">
          <Link href="/login">Back to sign in</Link>
        </p>
      </Card>
    </div>
  );
}
