import type { Metadata } from "next";
import type { ReactNode } from "react";
import { pageMetadata } from "@/lib/metadata";

export const metadata: Metadata = pageMetadata({
  title: "Explore",
  description: "Browse upcoming events across the San Francisco Bay Area. Filter by region, city, date, category and price, or see what is near you on the map.",
  path: "/explore",
});

export default function Layout({ children }: { children: ReactNode }) {
  return children;
}
