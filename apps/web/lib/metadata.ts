import type { Metadata } from "next";
import { SITE_DESCRIPTION, SITE_NAME } from "@/lib/site";

/** Pages that are personal, token-addressed or operational stay out of search results. */
export const NO_INDEX: Metadata["robots"] = { index: false, follow: false };

type PageMeta = {
  /** Page name; the root layout's template appends the site name. */
  title: string;
  description?: string;
  /** Site-relative canonical path. Omit for pages without one canonical URL. */
  path?: string;
  noindex?: boolean;
  /** Absolute https image for share cards, when the page has one. */
  image?: string | null;
};

/**
 * Title, description, canonical and share-card tags that agree with each
 * other. A segment that sets `openGraph` replaces the parent's whole object,
 * so every field a share card needs is restated here.
 */
export function pageMetadata({ title, description = SITE_DESCRIPTION, path, noindex = false, image }: PageMeta): Metadata {
  const shareTitle = `${title} | ${SITE_NAME}`;
  return {
    title,
    description,
    ...(path && !noindex ? { alternates: { canonical: path } } : {}),
    ...(noindex ? { robots: NO_INDEX } : {}),
    openGraph: {
      type: "website",
      siteName: SITE_NAME,
      locale: "en_US",
      title: shareTitle,
      description,
      ...(path ? { url: path } : {}),
      ...(image ? { images: [{ url: image }] } : {}),
    },
    twitter: {
      card: image ? "summary_large_image" : "summary",
      title: shareTitle,
      description,
      ...(image ? { images: [image] } : {}),
    },
  };
}

/** Collapse whitespace and cut at a word boundary for meta descriptions. */
export function summarize(text: string | null | undefined, maxLength = 200): string {
  const flat = (text ?? "").replace(/\s+/g, " ").trim();
  if (flat.length <= maxLength) return flat;
  const cut = flat.slice(0, maxLength - 1);
  const lastSpace = cut.lastIndexOf(" ");
  return `${(lastSpace > maxLength * 0.6 ? cut.slice(0, lastSpace) : cut).trimEnd()}…`;
}
