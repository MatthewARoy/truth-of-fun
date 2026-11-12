# Frontend Architecture: Web First, Mobile Ready

## Layout

- `apps/web`: Next.js website implementation.
- `packages/api-client`: shared endpoint contracts and HTTP client (consumable by any future client).

## Reuse Strategy

- Keep all backend payload types in `packages/api-client/src/types.ts`.
- Keep endpoint call logic in `packages/api-client/src/client.ts`.
- UI apps only compose these primitives in route/page components and hooks.

## Mobile Preparation Rules

1. Do not make direct `fetch()` calls in page components; use `@truth-of-fun/api-client`.
2. Keep route-level rendering concerns (`page.tsx`) separate from data hooks (`hooks/*`).
3. Add new endpoints to `api-client` first, then consume in client apps.

## Conventions added for launch

- **API base URLs.** `apps/web/lib/api/client.ts` holds the browser client;
  its base URL (`NEXT_PUBLIC_API_BASE_URL`) may be same-origin relative
  (`/api`). Server-side code (`generateMetadata`, `sitemap.ts`, server
  components) must use `apps/web/lib/api/server.ts`, which resolves an
  absolute URL (`API_INTERNAL_URL` first) and applies a short deadline. Never
  import the server helper from a client component.
- **Expired sessions.** The API client calls its `onUnauthorized` handler when
  a request that carried the stored token gets a 401. `AuthProvider` registers
  it once: it clears the stored session and navigates to
  `/login?reason=expired&next=<current path>`. Pages do not handle 401
  themselves. Sign-in, sign-up and password-reset calls are sent anonymously
  and never trigger it.
- **Shareable state lives in the URL.** Explore's filters are parsed from and
  written to the query string (`lib/explore-params.ts`) with
  `history.pushState`, which Next.js keeps in sync with `useSearchParams`.
  Component state is only for things that must not be shared (the "Near me"
  position) or are not worth a history entry.
- **Dates are Pacific.** Event times and date filters use
  `America/Los_Angeles` and a fixed display locale (`lib/localtime.ts`), so a
  server-rendered page and the browser produce identical text and a visitor
  in another timezone sees venue-local times.
- **Third-party listing data is untrusted.** Use `lib/event-format.ts`:
  `safeExternalUrl` (http/https only) for any href, `safeImageUrl` (https
  only) for any hotlinked image, `priceLabel` (never prints a price or "Free"
  the source did not state) and `eventStartLabel` (never prints a clock time
  for an estimated start).
- **Metadata.** Segment layouts build metadata with `pageMetadata()` from
  `lib/metadata.ts` (title template, canonical, Open Graph, Twitter).
  Personal, operational and token-addressed pages pass `noindex: true`.
  Share pages are deliberately *not* disallowed in `robots.ts`, so link-preview
  bots can read their tags.
- **Security headers** are set in `apps/web/next.config.ts`. A new third-party
  origin (script, image host over http, API, font) needs a CSP change there;
  `tests/e2e/csp.spec.ts` fails if a page triggers a violation.
- **Page structure.** The root layout renders the site header and nav outside
  `<main>`; every page renders exactly one `<h1>`.
