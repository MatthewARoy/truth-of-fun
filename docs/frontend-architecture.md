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
