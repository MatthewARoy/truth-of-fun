"use client";

import Link from "next/link";
import { useCallback, useEffect, useRef, useState } from "react";
import type { SharedItinerarySummary } from "@truth-of-fun/api-client";
import { apiClient } from "@/lib/api/client";
import { useAuth } from "@/lib/auth-context";
import { formatLocalDay, formatLocalTime } from "@/lib/localtime";
import { Button } from "@/components/ui/button";
import { CopyButton } from "@/components/copy-button";
import { InlineNotice } from "@/components/ui/inline-notice";

const PAGE_SIZE = 25;

export default function SharedPlansPage() {
  const { ready, token } = useAuth();
  if (!ready) return <InlineNotice>Loading shared plans...</InlineNotice>;
  if (!token) return (
    <section className="space-y-4">
      <h1 className="text-xl font-semibold">Shared plans</h1>
      <InlineNotice>Sign in to find and revoke your public links.</InlineNotice>
      <Link href="/login?next=%2Fshared-plans" className="text-brand-200 underline">Sign in to manage links</Link>
    </section>
  );
  return <SignedInSharedPlans key={token} />;
}

function SignedInSharedPlans() {
  const [plans, setPlans] = useState<SharedItinerarySummary[]>([]);
  const [offset, setOffset] = useState(0);
  const [hasMore, setHasMore] = useState(false);
  const [loading, setLoading] = useState(true);
  const [revoking, setRevoking] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const request = useRef<AbortController | null>(null);
  const mounted = useRef(false);

  const load = useCallback(async (nextOffset: number) => {
    request.current?.abort();
    const controller = new AbortController();
    request.current = controller;
    setLoading(true);
    setError(null);
    try {
      const page = await apiClient.getMyItineraries(PAGE_SIZE, nextOffset, { signal: controller.signal });
      if (controller.signal.aborted) return;
      setPlans((previous) => nextOffset === 0 ? page : [
        ...previous,
        ...page.filter((item) => !previous.some((plan) => plan.share_token === item.share_token)),
      ]);
      setOffset(nextOffset);
      setHasMore(page.length === PAGE_SIZE);
    } catch (err) {
      if (!controller.signal.aborted) setError(err instanceof Error ? err.message : "Could not load shared plans");
    } finally {
      if (!controller.signal.aborted) setLoading(false);
    }
  }, []);

  useEffect(() => {
    mounted.current = true;
    void load(0);
    return () => {
      mounted.current = false;
      request.current?.abort();
    };
  }, [load]);

  useEffect(() => {
    const nextExpiry = Math.min(...plans.filter((plan) => plan.status === "active").map((plan) => Date.parse(plan.expires_at)));
    if (!Number.isFinite(nextExpiry)) return;
    // Update only statuses so reaching an expiry preserves loaded pages. A
    // focus check also covers background tabs whose timers were suspended.
    const markExpired = () => setPlans((previous) => previous.map((plan) =>
      plan.status === "active" && Date.parse(plan.expires_at) <= Date.now()
        ? { ...plan, status: "expired" }
        : plan));
    const timer = window.setTimeout(markExpired, Math.min(Math.max(0, nextExpiry - Date.now()), 2_147_483_647));
    window.addEventListener("focus", markExpired);
    return () => {
      window.clearTimeout(timer);
      window.removeEventListener("focus", markExpired);
    };
  }, [plans]);

  async function revoke(plan: SharedItinerarySummary) {
    if (revoking) return;
    // A list request started before the delete must not restore an active row.
    request.current?.abort();
    setLoading(false);
    setRevoking(plan.share_token);
    setError(null);
    setNotice(null);
    try {
      await apiClient.revokeItinerary(plan.share_token);
      if (!mounted.current) return;
      setPlans((previous) => previous.map((item) => item.share_token === plan.share_token
        ? { ...item, status: "revoked", revoked_at: new Date().toISOString() }
        : item));
      setNotice(`Link revoked for ${plan.title}. People opening it can no longer read the plan.`);
    } catch (err) {
      if (mounted.current) setError(err instanceof Error ? err.message : "Could not revoke the link");
    } finally {
      if (mounted.current) setRevoking(null);
    }
  }

  return (
    <section className="mx-auto max-w-2xl space-y-4">
      <h1 className="text-xl font-semibold">Shared plans</h1>
      <p className="text-sm text-slate-400">
        Anyone with an active link can read its event plan until it expires or you revoke it.
        Your original request stays private. Revoking cannot remove copies someone already saved.
      </p>
      <div className="flex items-center gap-4">
        <Link href="/planner" className="text-brand-200 underline">Plan something new</Link>
        <Button variant="secondary" onClick={() => void load(0)} disabled={loading || Boolean(revoking)}>Refresh</Button>
      </div>
      {notice && <p role="status" className="text-sm text-brand-200">{notice}</p>}
      {error && <InlineNotice tone="error">{error}. Try again using Refresh or Revoke link.</InlineNotice>}
      {loading && <InlineNotice>Loading shared plans...</InlineNotice>}
      {!loading && !error && plans.length === 0 && <InlineNotice>No public links yet. Build a plan, then choose Create public link.</InlineNotice>}
      <ul className="space-y-3">
        {plans.map((plan) => {
          const status = plan.status;
          return (
            <li key={plan.share_token} className="space-y-3 rounded-ui border border-slate-800 bg-slate-900 p-4">
              <div className="space-y-1">
                {status === "active"
                  ? <Link href={plan.share_url} className="font-semibold text-brand-200 underline">{plan.title}</Link>
                  : <h2 className="font-semibold">{plan.title}</h2>}
                <p className="text-sm">{status === "active" ? "Active" : status === "revoked" ? "Revoked" : "Expired"}</p>
                <p className="text-xs text-slate-400">
                  Created {formatLocalDay(plan.created_at)}. Expires {formatLocalDay(plan.expires_at)} at {formatLocalTime(plan.expires_at)} Pacific time.
                </p>
              </div>
              <div className="flex flex-wrap gap-2">
                {status === "active" && <CopyButton label="Copy link" value={`${window.location.origin}${plan.share_url}`} />}
                {status !== "revoked" && (
                  <Button variant="danger" onClick={() => void revoke(plan)} disabled={Boolean(revoking)}>
                    {revoking === plan.share_token ? "Revoking..." : "Revoke link"}
                  </Button>
                )}
              </div>
            </li>
          );
        })}
      </ul>
      {hasMore && <Button onClick={() => void load(offset + PAGE_SIZE)} disabled={loading || Boolean(revoking)} variant="secondary">Load more</Button>}
    </section>
  );
}
