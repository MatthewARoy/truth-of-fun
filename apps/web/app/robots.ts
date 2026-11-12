import type { MetadataRoute } from "next";
import { SITE_URL } from "@/lib/site";

// Personal and operational areas are kept away from crawlers. The share pages
// (/itinerary/<token>, /shared/folders/<token>) are deliberately NOT listed:
// link-preview bots obey robots.txt, and blocking them would strip the share
// card. Those pages carry a `noindex` robots meta tag instead.
export default function robots(): MetadataRoute.Robots {
  return {
    rules: {
      userAgent: "*",
      allow: "/",
      disallow: [
        "/admin/",
        "/account",
        "/folders",
        "/invites/",
        "/shared-plans",
        "/onboarding",
        "/recommendations",
        "/reset-password",
        "/healthz",
      ],
    },
    sitemap: `${SITE_URL}/sitemap.xml`,
    host: SITE_URL,
  };
}
