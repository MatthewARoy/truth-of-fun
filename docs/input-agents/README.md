# Input Agents

This directory defines source-specific input agents for event ingestion. The reference deployment is configured for SF Bay Area sources; agents can be added/removed for other regions.

Each agent spec is designed to support:
- API-based ingestion where available
- Scraper-based ingestion where needed
- Account credential and session management
- Canonical schema normalization for downstream dedupe/recommendation

## Source Agents
- [Ticketmaster](./source-ticketmaster.md)
- [Eventbrite](./source-eventbrite.md)
- [Meetup](./source-meetup.md)
- [FuncheapSF](./source-funcheapsf.md)
- [19hz](./source-19hz.md)
- [Luma](./source-luma.md)
- [DoTheBay](./source-dothebay.md)
- [SF Station](./source-sfstation.md)
- [Minnesota Street Project + Arts Venues](./source-minnesota-street-arts.md)
- [Reddit (r/AskSF, r/bayarea, r/sanfrancisco)](./source-reddit.md)
- [Newsletters (Eddie's List)](./source-newsletters-eddies-list.md)

## Shared Standards
- [Canonical Schema + Strategy](./canonical-schema-and-strategy.md)

## Notes
- For all sources, retain the source URL and deep-link users back to original providers.
