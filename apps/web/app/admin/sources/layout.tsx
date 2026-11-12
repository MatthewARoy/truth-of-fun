import type { Metadata } from "next";
import type { ReactNode } from "react";
import { pageMetadata } from "@/lib/metadata";

export const metadata: Metadata = pageMetadata({
  title: "Source health",
  description: "Operator view of event source health.",
  noindex: true,
});

export default function Layout({ children }: { children: ReactNode }) {
  return children;
}
