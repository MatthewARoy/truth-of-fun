import type { Metadata } from "next";
import type { ReactNode } from "react";
import { pageMetadata } from "@/lib/metadata";

export const metadata: Metadata = pageMetadata({
  title: "Planner",
  description: "Describe the day or night out you want in plain English and get a sequenced Bay Area itinerary with time to travel between stops.",
  path: "/planner",
});

export default function Layout({ children }: { children: ReactNode }) {
  return children;
}
