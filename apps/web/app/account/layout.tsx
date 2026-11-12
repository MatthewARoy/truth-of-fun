import type { Metadata } from "next";
import type { ReactNode } from "react";
import { pageMetadata } from "@/lib/metadata";

export const metadata: Metadata = pageMetadata({
  title: "Account",
  description: "Manage your Truth of Fun account, interests, password and data.",
  noindex: true,
});

export default function Layout({ children }: { children: ReactNode }) {
  return children;
}
