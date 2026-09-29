"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useEffect, useState } from "react";
import type { EventResponse, FolderDetailResponse, InviteResponse, RecommendationResponse } from "@truth-of-fun/api-client";
import { apiClient } from "@/lib/api/client";
import { useAuth } from "@/lib/auth-context";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { InlineNotice } from "@/components/ui/inline-notice";
import { Input } from "@/components/ui/input";
import { formatLocalDay } from "@/lib/localtime";

export default function FolderDetailPage() {
  const params = useParams<{ folderId: string }>();
  const folderId = Number(params.folderId);
  const { ready, token } = useAuth();
  if (!ready) return <InlineNotice>Loading folder...</InlineNotice>;
  if (!token) return (
    <section className="space-y-4">
      <h2 className="text-xl font-semibold">Folder Detail</h2>
      <InlineNotice tone="info">Sign in to view this folder.</InlineNotice>
    </section>
  );
  if (!Number.isSafeInteger(folderId) || folderId < 1) return <InlineNotice tone="error">Invalid folder.</InlineNotice>;
  return <SignedInFolder key={`${token}:${folderId}`} folderId={folderId} />;
}

function SignedInFolder({ folderId }: { folderId: number }) {
  const [folder, setFolder] = useState<FolderDetailResponse | null>(null);
  const [invite, setInvite] = useState<InviteResponse | null>(null);
  const [copied, setCopied] = useState(false);
  const [exploreEvents, setExploreEvents] = useState<EventResponse[]>([]);
  const [recommendations, setRecommendations] = useState<RecommendationResponse[]>([]);
  const [vibeFilter, setVibeFilter] = useState("");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [refreshVersion, setRefreshVersion] = useState(0);
  const [suggestionsLoading, setSuggestionsLoading] = useState(true);
  const [suggestionError, setSuggestionError] = useState<string | null>(null);

  useEffect(() => {
    const controller = new AbortController();
    setLoading(true);
    setError(null);
    void apiClient.getFolder(folderId, { signal: controller.signal }).then((response) => {
      if (!controller.signal.aborted) setFolder(response);
    }).catch((err) => {
      if (!controller.signal.aborted) setError(err instanceof Error ? err.message : "Could not load folder.");
    }).finally(() => {
      if (!controller.signal.aborted) setLoading(false);
    });
    void apiClient.getRecommendations(6, 0, { signal: controller.signal }).then((response) => {
      if (!controller.signal.aborted) setRecommendations(response);
    }).catch((err) => {
      if (!controller.signal.aborted) setError(err instanceof Error ? err.message : "Could not load recommendations.");
    });
    return () => controller.abort();
  }, [folderId, refreshVersion]);

  useEffect(() => {
    const controller = new AbortController();
    setSuggestionsLoading(true);
    setExploreEvents([]);
    setSuggestionError(null);
    const timer = setTimeout(() => {
      void apiClient.getEvents({ limit: 8, time_preset: "this_weekend", vibe_tag: vibeFilter.trim() || undefined }, {
        signal: controller.signal,
      }).then((response) => {
        if (!controller.signal.aborted) setExploreEvents(response);
      }).catch((err) => {
        if (!controller.signal.aborted) setSuggestionError(err instanceof Error ? err.message : "Could not load suggestions.");
      }).finally(() => {
        if (!controller.signal.aborted) setSuggestionsLoading(false);
      });
    }, 300);
    return () => { clearTimeout(timer); controller.abort(); };
  }, [vibeFilter, refreshVersion]);

  async function addItem(eventId: number) {
    setError(null);
    try {
      const response = await apiClient.addFolderItem(folderId, eventId);
      setFolder(response);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Unknown error");
    }
  }

  async function vote(folderItemId: number, value: number) {
    setError(null);
    try {
      const response = await apiClient.voteFolderItem(folderId, folderItemId, value);
      setFolder(response);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Unknown error");
    }
  }

  async function generateInvite() {
    setError(null);
    setCopied(false);
    try {
      const response = await apiClient.createFolderInvite(folderId);
      setInvite(response);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Unknown error");
    }
  }

  async function copyInviteLink() {
    if (!invite) return;
    try {
      await navigator.clipboard.writeText(
        `${window.location.origin}/invites/${invite.invite_token}`
      );
      setCopied(true);
      window.setTimeout(() => setCopied(false), 2000);
    } catch {
      setError("Could not copy the link — copy it manually instead.");
    }
  }

  async function revokeInvite() {
    if (!invite) return;
    setError(null);
    setCopied(false);
    try {
      await apiClient.revokeFolderInvite(folderId, invite.invite_token);
      setInvite(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Unknown error");
    }
  }

  // Share links leave the app, so they need the full origin, not a relative path.
  const absoluteShareUrl =
    invite && typeof window !== "undefined"
      ? `${window.location.origin}${invite.share_url}`
      : invite?.share_url ?? null;
  const absoluteInviteUrl =
    invite && typeof window !== "undefined"
      ? `${window.location.origin}/invites/${invite.invite_token}`
      : null;

  return (
    <section className="space-y-4">
      <h2 className="text-xl font-semibold">Folder Detail</h2>
      {loading ? <InlineNotice>Loading folder...</InlineNotice> : null}
      {error ? <InlineNotice tone="error">Error: {error}</InlineNotice> : null}
      {folder ? (
        <Card className="space-y-3">
          <p className="font-medium">{folder.name}</p>
          <div className="flex flex-wrap gap-2">
            <Button type="button" onClick={() => void generateInvite()} variant="secondary">
              Generate share link
            </Button>
            <Button type="button" variant="ghost" onClick={() => setRefreshVersion((version) => version + 1)}>
              Refresh suggestions
            </Button>
          </div>
          {invite ? (
            <div className="space-y-1 text-sm text-emerald-200">
              <div className="flex flex-wrap items-center gap-2">
                <span className="break-all">
                  Invite link (can vote):{" "}
                  <Link href={`/invites/${invite.invite_token}`}>{absoluteInviteUrl}</Link>
                </span>
                <Button type="button" variant="ghost" size="sm" onClick={() => void copyInviteLink()}>
                  {copied ? "Copied" : "Copy link"}
                </Button>
                <Button type="button" variant="ghost" size="sm" onClick={() => void revokeInvite()}>
                  Revoke
                </Button>
              </div>
              <p className="break-all text-slate-400">
                View-only link: <Link href={invite.share_url}>{absoluteShareUrl}</Link>
              </p>
              {invite.expires_at ? (
                <p className="text-slate-400">
                  Expires {new Date(invite.expires_at).toLocaleDateString()}
                </p>
              ) : null}
            </div>
          ) : null}
          {folder.items.length === 0 ? <InlineNotice>No items yet.</InlineNotice> : null}
          <ul className="space-y-2">
            {folder.items.map((item) => (
              <li key={item.folder_item_id} className="rounded-ui border border-slate-700 p-3">
                <div className="flex items-center justify-between gap-3">
                  <p>{item.event_title}</p>
                  <p className="text-sm text-slate-300">Score: {item.vote_score}</p>
                </div>
                <div className="mt-2 flex gap-2">
                  <Button
                    type="button"
                    onClick={() => void vote(item.folder_item_id, 1)}
                    variant="secondary"
                    size="sm"
                  >
                    Upvote
                  </Button>
                  <Button
                    type="button"
                    onClick={() => void vote(item.folder_item_id, -1)}
                    variant="secondary"
                    size="sm"
                  >
                    Downvote
                  </Button>
                </div>
              </li>
            ))}
          </ul>
        </Card>
      ) : null}

      <Card className="space-y-3">
        <h3 className="text-base font-semibold">Add from suggested events</h3>
        <Input
          label="Vibe filter (optional)"
          placeholder="#Chill"
          value={vibeFilter}
          onChange={(event) => setVibeFilter(event.target.value)}
        />
        <div className="grid gap-2">
          {suggestionsLoading ? <InlineNotice>Loading suggestions...</InlineNotice> : null}
          {suggestionError ? <InlineNotice tone="error">{suggestionError}</InlineNotice> : null}
          {exploreEvents.map((event) => (
            <div key={event.id} className="flex items-center justify-between rounded-ui border border-slate-800 p-2">
              <p className="text-sm">
                {event.title} <span className="text-slate-400">({formatLocalDay(event.start_at)})</span>
              </p>
              <Button type="button" size="sm" onClick={() => void addItem(event.id)}>
                Add
              </Button>
            </div>
          ))}
          {!suggestionsLoading && !suggestionError && exploreEvents.length === 0 ? <p className="text-sm text-slate-400">No explore suggestions right now.</p> : null}
        </div>
      </Card>

      <Card className="space-y-3">
        <h3 className="text-base font-semibold">Add from recommendations</h3>
        <div className="grid gap-2">
          {recommendations.map((event) => (
            <div key={event.id} className="flex items-center justify-between rounded-ui border border-slate-800 p-2">
              <p className="text-sm">
                {event.title} <span className="text-brand-200">(match {event.match_score})</span>
              </p>
              <Button type="button" size="sm" onClick={() => void addItem(event.id)}>
                Add
              </Button>
            </div>
          ))}
          {recommendations.length === 0 ? (
            <p className="text-sm text-slate-400">No recommendations yet. Complete onboarding to improve this list.</p>
          ) : null}
        </div>
      </Card>
    </section>
  );
}
