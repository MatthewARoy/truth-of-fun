import type { Metadata } from "next";
import type { ReactNode } from "react";
import { SERVER_REQUEST, serverApiClient } from "@/lib/api/server";
import { pageMetadata, summarize } from "@/lib/metadata";

const GENERIC = pageMetadata({
  title: "Shared folder",
  description: "A shortlist of Bay Area events, shared from Truth of Fun.",
  noindex: true,
});

// Never indexed (the link is the credential); fails soft to generic text when
// the API is unreachable or the token is unknown.
export async function generateMetadata(
  { params }: { params: Promise<{ token: string }> }
): Promise<Metadata> {
  const { token } = await params;
  if (!token || token.length > 200) return GENERIC;
  try {
    const folder = await serverApiClient().getSharedFolder(token, SERVER_REQUEST);
    if (!folder?.name) return GENERIC;
    const titles = (folder.items ?? []).map((item) => item.event_title).filter(Boolean);
    const description = titles.length > 0
      ? summarize(`${titles.length} ${titles.length === 1 ? "event" : "events"} on the shortlist: ${titles.join(", ")}`, 200)
      : "A shortlist of Bay Area events, shared from Truth of Fun.";
    return pageMetadata({ title: summarize(folder.name, 110), description, noindex: true });
  } catch {
    return GENERIC;
  }
}

export default function Layout({ children }: { children: ReactNode }) {
  return children;
}
