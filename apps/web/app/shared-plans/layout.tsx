import type { Metadata } from "next";
import type { ReactNode } from "react";
import { pageMetadata } from "@/lib/metadata";

export const metadata: Metadata = pageMetadata({
  title: "Your shared plans",
  description: "Manage the public links to plans you have shared.",
  noindex: true,
});

export default function Layout({ children }: { children: ReactNode }) {
  return children;
}
