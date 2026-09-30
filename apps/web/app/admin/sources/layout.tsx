import type { Metadata } from "next";
import type { ReactNode } from "react";

export const metadata: Metadata = { title: "Source health | Truth of Fun" };

export default function Layout({ children }: { children: ReactNode }) {
  return children;
}
