import type { Metadata } from "next";
import type { ReactNode } from "react";
import { pageMetadata } from "@/lib/metadata";

export const metadata: Metadata = pageMetadata({
  title: "Recommendations",
  description: "Events picked for you based on what you save and like.",
  noindex: true,
});

export default function Layout({ children }: { children: ReactNode }) {
  return children;
}
