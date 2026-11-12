import type { Metadata } from "next";
import type { ReactNode } from "react";
import { pageMetadata } from "@/lib/metadata";

export const metadata: Metadata = pageMetadata({
  title: "Sign in",
  description: "Sign in or create a Truth of Fun account to save events and get recommendations.",
  noindex: true,
});

export default function Layout({ children }: { children: ReactNode }) {
  return children;
}
