import type { Metadata } from "next";
import type { ReactNode } from "react";
import { SERVER_REQUEST, serverApiClient } from "@/lib/api/server";
import { pageMetadata, summarize } from "@/lib/metadata";

const GENERIC = pageMetadata({
  title: "Shared itinerary",
  description: "A plan for a day or night out around the Bay Area, shared from Truth of Fun.",
  noindex: true,
});

// The link is the credential, so these pages are never indexed. The share
// card still shows the plan's own title and stops — the same public snapshot
// the page renders — and falls back to generic text if the API cannot be
// reached or the link is unknown, expired or revoked.
export async function generateMetadata(
  { params }: { params: Promise<{ token: string }> }
): Promise<Metadata> {
  const { token } = await params;
  if (!token || token.length > 200) return GENERIC;
  try {
    const plan = await serverApiClient().getSharedItinerary(token, SERVER_REQUEST);
    if (!plan?.title || Date.parse(plan.expires_at) <= Date.now()) return GENERIC;
    const stops = (plan.itinerary ?? []).map((stop) => stop.title).filter(Boolean);
    const description = stops.length > 0
      ? summarize(`${stops.length} ${stops.length === 1 ? "stop" : "stops"}: ${stops.join(" → ")}`, 200)
      : "A plan shared from Truth of Fun.";
    return pageMetadata({ title: summarize(plan.title, 110), description, noindex: true });
  } catch {
    return GENERIC;
  }
}

export default function Layout({ children }: { children: ReactNode }) {
  return children;
}
