# Input Agent Spec: Meetup GraphQL

## Source Summary
- Source ID: `meetup`
- Type: API (GraphQL)
- Strategic role: recurring community events and group-driven social signal

## Access and Accounts
- Account type: API token/OAuth per app setup
- Rate model: points-based budget (e.g., 500 points / 60s)
- Account strategy:
  - separate app/account for production ingestion
  - query-cost monitoring and schema change watch

## Ingestion Strategy
- Endpoint: `https://api.meetup.com/gql-ext`
- Query design:
  - request only needed fields
  - keep query complexity low to avoid throttling
- Sync cadence: frequent incremental pulls for near-term events

## Field Mapping
- event title/date/location fields -> canonical title/time/location
- group name/url -> `organizer.*`
- RSVP/attendance data -> `social_signals.attendee_count`
- event URL -> `source.source_url`

## Quality and Risk Controls
- Preserve group context for recommendations
- Handle recurring templates vs individual occurrences
- Validate GraphQL response shape and partial errors

## Operational Metrics
- query point usage and throttle events
- event freshness lag
- % records with organizer/group metadata
