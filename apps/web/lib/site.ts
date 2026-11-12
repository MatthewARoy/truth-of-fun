/** Product name and the public origin used for canonical and share URLs. */
export const SITE_NAME = "Truth of Fun";

export const SITE_TAGLINE = "Things to do around the San Francisco Bay Area";

export const SITE_DESCRIPTION =
  "Find concerts, comedy, food, outdoor and community events across San Francisco, the East Bay, "
  + "the Peninsula, the South Bay and the North Bay, and plan a day or night out.";

/**
 * `NEXT_PUBLIC_SITE_URL` is the origin people reach the site at, e.g.
 * `https://example.com`. It is inlined at build time. The fallback only keeps
 * local development and tests working; production must set it, otherwise
 * canonical links and share cards point at localhost.
 */
export const SITE_URL = (() => {
  const configured = process.env.NEXT_PUBLIC_SITE_URL?.trim();
  if (configured) {
    try {
      const url = new URL(configured);
      if (url.protocol === "https:" || url.protocol === "http:") return url.origin;
    } catch {
      // fall through to the development default
    }
  }
  return "http://localhost:3000";
})();

export function absoluteUrl(path: string): string {
  return new URL(path, SITE_URL).toString();
}
