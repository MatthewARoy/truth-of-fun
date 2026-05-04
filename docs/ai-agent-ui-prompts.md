# AI Agent Prompt Pack: UI Bootstrapping

Use these prompts as isolated tasks for autonomous agents.

## Prompt 1: Scaffold web app

Create `apps/web` in this repo using Next.js (App Router) + TypeScript + Tailwind. Add a clean folder structure (`app`, `components`, `lib/api`, `lib/types`, `hooks`). Configure `.env.local` with `NEXT_PUBLIC_API_BASE_URL`. Add npm scripts for `dev`, `build`, `lint`, and document setup in `apps/web/README.md`.

## Prompt 2: Build typed API layer

Implement a typed API client in `packages/api-client` for these endpoints: `/events`, `/recommendations`, `/users/me/onboarding`, `/users/me/interests`, `/concierge/itinerary`, `/folders`, `/shared/folders/{token}`. Include request/response TypeScript types, error normalization, and simple retry for idempotent GETs.

## Prompt 3: Build Explore + Recommendations pages

Build `Explore` and `Recommendations` pages in `apps/web` using the shared API client. Explore must support filters (vibe, time window, optional geospatial search). Recommendation cards must show matched vibes and score. Add loading, empty, and error states.

## Prompt 4: Build onboarding and event actions

Create an onboarding flow with a `Perfect Saturday` text input calling `POST /users/me/onboarding`, then navigate to recommendations. Add event card actions for save/like/click via `POST /users/me/interests` and optimistic UI updates.

## Prompt 5: Build concierge planner

Create a concierge page with natural-language input and itinerary rendering from `POST /concierge/itinerary`. Show intent, timeframe, geography, and ordered stops with travel buffer labels.

## Prompt 6: Build social folders and share view

Create folder management UI for creating folders, adding events, voting, generating invite links, and rendering a public read-only shared folder view from token routes.

## Prompt 7: Add quality gates

Add Playwright E2E tests for onboarding -> recommendations, explore -> save, concierge itinerary generation, and folder share-view rendering. Add CI workflow for web lint/typecheck/tests.
