import type { NextConfig } from "next";

const isDev = process.env.NODE_ENV === "development";

// The browser talks to the API directly. When the API is on another origin
// (local development: http://127.0.0.1:8000) that origin must be allowed in
// connect-src; in production the API is same-origin under /api and 'self'
// already covers it. NEXT_PUBLIC_API_BASE_URL is a build-time value, the same
// one inlined into the client bundle (see lib/api/client.ts).
function apiOrigin(): string | null {
  const base = process.env.NEXT_PUBLIC_API_BASE_URL || "http://127.0.0.1:8000";
  if (!/^https?:\/\//i.test(base)) return null;
  try {
    return new URL(base).origin;
  } catch {
    return null;
  }
}

const connectSrc = ["'self'", apiOrigin(), isDev ? "ws:" : null].filter(Boolean).join(" ");

// No nonces: pages are statically prerendered, so Next's inline bootstrap
// scripts and inline styles need 'unsafe-inline'. React needs eval only in
// development (for reconstructing server error stacks).
//   img-src   https: — event images are hotlinked from many third-party hosts,
//             and the map tiles come from CARTO's CDN (*.basemaps.cartocdn.com).
//   style-src 'unsafe-inline' — Next inline styles and Leaflet's positioned markers.
// There is no upgrade-insecure-requests: it would rewrite the plain-http API
// calls made during local development. HSTS covers production.
const contentSecurityPolicy = [
  "default-src 'self'",
  `script-src 'self' 'unsafe-inline'${isDev ? " 'unsafe-eval'" : ""}`,
  "style-src 'self' 'unsafe-inline'",
  "img-src 'self' data: blob: https:",
  "font-src 'self' data:",
  `connect-src ${connectSrc}`,
  "worker-src 'self' blob:",
  "manifest-src 'self'",
  "object-src 'none'",
  "base-uri 'self'",
  "form-action 'self'",
  "frame-ancestors 'none'",
].join("; ");

const nextConfig: NextConfig = {
  output: "standalone",
  poweredByHeader: false,
  allowedDevOrigins: ["127.0.0.1", "localhost"],
  async headers() {
    return [
      {
        source: "/:path*",
        headers: [
          { key: "Content-Security-Policy", value: contentSecurityPolicy },
          // Browsers ignore HSTS over plain http, so this is inert in local development.
          // No includeSubDomains/preload: that is a decision about the whole
          // domain, to be made at the edge proxy, not by this app.
          { key: "Strict-Transport-Security", value: "max-age=31536000" },
          { key: "X-Content-Type-Options", value: "nosniff" },
          { key: "X-Frame-Options", value: "DENY" },
          { key: "Referrer-Policy", value: "strict-origin-when-cross-origin" },
          // geolocation=(self): Explore's "Near me" asks for the browser's position.
          { key: "Permissions-Policy", value: "camera=(), microphone=(), geolocation=(self)" },
        ],
      },
    ];
  },
};

export default nextConfig;
