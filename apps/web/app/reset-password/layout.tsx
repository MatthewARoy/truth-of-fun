import type { Metadata } from "next";
import type { ReactNode } from "react";
import { pageMetadata } from "@/lib/metadata";

export const metadata: Metadata = {
  ...pageMetadata({
    title: "Choose a new password",
    description: "Set a new password for your Truth of Fun account.",
    noindex: true,
  }),
  // The reset token is in the URL; never send it on in a Referer header.
  referrer: "no-referrer",
};

export default function Layout({ children }: { children: ReactNode }) {
  return children;
}
