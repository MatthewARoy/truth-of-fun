import type { Metadata } from "next";
import type { ReactNode } from "react";
import { pageMetadata } from "@/lib/metadata";

export const metadata: Metadata = pageMetadata({
  title: "Folder details",
  description: "A shortlist of events to vote on with friends.",
  noindex: true,
});

export default function Layout({ children }: { children: ReactNode }) {
  return children;
}
