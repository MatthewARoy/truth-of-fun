"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { ApiClientError } from "@truth-of-fun/api-client";
import { apiClient } from "@/lib/api/client";
import { useAuth } from "@/lib/auth-context";
import { PASSWORD_MIN_LENGTH, passwordProblem } from "@/lib/password";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { InlineNotice } from "@/components/ui/inline-notice";
import { Input } from "@/components/ui/input";

export default function ResetPasswordPage() {
  const router = useRouter();
  const { setSession } = useAuth();
  // undefined until the URL has been read in the browser; null when absent.
  const [token, setToken] = useState<string | null | undefined>(undefined);
  const [password, setPassword] = useState("");
  const [confirmation, setConfirmation] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  // The API rejected the token itself (expired, used, or unknown).
  const [linkRejected, setLinkRejected] = useState(false);

  useEffect(() => {
    setToken(new URLSearchParams(window.location.search).get("token")?.trim() || null);
  }, []);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!token) return;
    const problem = passwordProblem(password);
    if (problem) return setError(problem);
    if (password !== confirmation) return setError("The two passwords do not match.");
    setLoading(true);
    setError(null);
    setLinkRejected(false);
    try {
      const response = await apiClient.confirmPasswordReset({ token, new_password: password });
      // The API answers like a login, so the user is signed in straight away.
      setSession(response);
      // replace(): the token-bearing URL should not stay in the history.
      router.replace("/explore");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not reset your password. Please try again.");
      setLinkRejected(err instanceof ApiClientError && err.status === 400);
      setLoading(false);
    }
  }

  return (
    <div className="mx-auto max-w-sm space-y-6">
      <Card className="space-y-5">
        <div className="space-y-1">
          <h1 className="text-xl font-semibold">Choose a new password</h1>
          <p className="text-sm text-slate-400">
            Setting a new password signs you in here and signs out your other devices.
          </p>
        </div>

        {token === null ? (
          <div className="space-y-4">
            <InlineNotice tone="error">
              This reset link is incomplete. Open the link from your email again, or request a new one.
            </InlineNotice>
            <p className="text-center text-sm">
              <Link href="/forgot-password">Request a new reset link</Link>
            </p>
          </div>
        ) : (
          <form onSubmit={handleSubmit} className="space-y-4">
            <Input
              label="New password"
              type="password"
              name="new-password"
              autoComplete="new-password"
              hint={`At least ${PASSWORD_MIN_LENGTH} characters.`}
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              required
              minLength={PASSWORD_MIN_LENGTH}
            />
            <Input
              label="Confirm new password"
              type="password"
              name="confirm-password"
              autoComplete="new-password"
              value={confirmation}
              onChange={(e) => setConfirmation(e.target.value)}
              required
            />
            {error ? (
              <InlineNotice tone="error">
                {error}
                {linkRejected ? (
                  <>
                    {" "}
                    <Link href="/forgot-password" className="underline">Request a new link</Link>
                  </>
                ) : null}
              </InlineNotice>
            ) : null}
            <Button type="submit" fullWidth disabled={loading || token === undefined}>
              {loading ? "Saving..." : "Set new password"}
            </Button>
          </form>
        )}
      </Card>
    </div>
  );
}
