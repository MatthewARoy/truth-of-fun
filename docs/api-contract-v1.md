# API Contract v1 (UI Baseline)

This contract freezes the initial web/mobile-facing payloads for the first UI release.

## Discovery

- `GET /events`
- `GET /recommendations`
- `POST /users/me/onboarding`
- `POST /users/me/interests`
- `POST /concierge/itinerary`

## Social

- `GET /folders`
- `POST /folders`
- `GET /folders/{folder_id}`
- `POST /folders/{folder_id}/items`
- `POST /folders/{folder_id}/votes`
- `POST /folders/{folder_id}/invite`
- `GET /shared/folders/{token}`

## Notes

- Current user identity is single-user dev mode (`me@local.dev`).
- Contract changes should be additive while web and mobile clients are bootstrapping.
