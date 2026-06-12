"use client";

import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { useEffect, useRef, useState } from "react";
import { apiClient } from "@/lib/api/client";
import { useAuth } from "@/lib/auth-context";
import { InlineNotice } from "@/components/ui/inline-notice";

export default function AcceptInvitePage() {
  const params = useParams<{ token: string }>();
  const router = useRouter();
  const { ready, token } = useAuth();
  const [error, setError] = useState<string | null>(null);
  const accepted = useRef(false);

  useEffect(() => {
    if (!ready || !token || accepted.current) return;
    accepted.current = true;
    apiClient
      .acceptFolderInvite(params.token)
      .then((folder) => {
        router.replace(`/folders/${folder.id}`);
      })
      .catch((err) => {
        setError(err instanceof Error ? err.message : "Unknown error");
      });
  }, [ready, token, params.token, router]);

  return (
    <section className="space-y-4">
      <h2 className="text-xl font-semibold">Folder invite</h2>
      {ready && !token ? (
        <InlineNotice tone="info">
          <Link href="/login" className="underline">
            Sign in
          </Link>{" "}
          to join this folder and vote on the plan.
        </InlineNotice>
      ) : null}
      {!error && token ? <InlineNotice>Joining folder...</InlineNotice> : null}
      {error ? <InlineNotice tone="error">Error: {error}</InlineNotice> : null}
    </section>
  );
}
