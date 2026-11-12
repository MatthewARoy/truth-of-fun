import type { Metadata } from "next";
import type { ReactNode } from "react";
import { pageMetadata } from "@/lib/metadata";

export const metadata: Metadata = pageMetadata({
  title: "Reset your password",
  description: "Request a link to reset your Truth of Fun password.",
  noindex: true,
});

export default function Layout({ children }: { children: ReactNode }) {
  return children;
}
