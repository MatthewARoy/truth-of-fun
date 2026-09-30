# Named dinner/drinks stops: Places evaluation (#31)

Recommendation: preserve the Maps-search fallback while choosing a provider-compatible sharing model. Google Places (New) is the strongest candidate for explicitly reported kitchen hours; Foursquare's new API is the lower-cost candidate for business-hours-aware search. Neither should be silently wired into permanent public text snapshots before retention/display rules are resolved. No provider key, paid account or connector was activated.

## API and cost comparison, checked September 29, 2026

| Choice | Useful capability | Marginal plan cost assumption | Constraint |
| --- | --- | --- | --- |
| Google Places (New) | Nearby/Text search, reported current and secondary hours, including kitchen hours | Two Enterprise searches at $35/1,000 = $0.07 after SKU free caps; a secondary-hours field must remain in the explicit field mask | Content retention/display restrictions conflict with copying names/hours into indefinite immutable snapshots |
| Foursquare new Places API | Nearby/category search and `open_at` at a local weekday/time, excluding missing hours | Two Pro calls at $15/1,000 = $0.03 after its first 500 Pro calls; Premium fields may instead cost $18.75/1,000, or $0.0375 for two | General venue opening is not kitchen service; account-specific retention must be established |
| OSM-derived licensed/self-hosted POI source | Geography and potentially community-supplied opening_hours | No paid per-call assumption; hosting/updates/validation costs still exist | Sparse/unverified service hours and licensing/attribution work; public Nominatim is not a generic production POI-search backend |

Costs are conditional calculations from current published tiers, excluding refreshes/details/retries, volume discounts, other SKUs and any taxes. No claim is made about actual billed spend. Google lists a 1,000-call Enterprise free usage cap per relevant SKU. A worst-case refresh policy must be budgeted separately; public page views must not create unlimited paid lookups.

Sources: [Google pricing](https://developers.google.com/maps/billing-and-pricing/pricing), [field tiers](https://developers.google.com/maps/documentation/places/web-service/data-fields), [secondary hours types](https://developers.google.com/maps/documentation/places/web-service/reference/rest/v1/places), [Foursquare pricing](https://foursquare.com/pricing/), [new search open_at](https://docs.foursquare.com/fsq-developers-places/reference/place-search), [legacy endpoint retirement](https://docs.foursquare.com/developer/reference/upcoming-changes).

## Retention and provenance decision

Google's [Places policies](https://developers.google.com/maps/documentation/places/web-service/policies) restrict storage/caching except permitted exceptions such as place IDs and require Google/third-party attribution. Keep provider names, hours and coordinates out of durable shared snapshots unless the applicable agreement explicitly permits them. Public pages could instead retain provider IDs, planning/fetch timestamps and freshly fetch display facts, but that changes today's frozen-snapshot behavior and per-view cost. A short cache TTL does not itself confer permission.

Foursquare's [self-service EULA](https://foursquare.com/legal/terms/apilicenseagreement/) delegates caching limits to account-specific [Usage Guidelines](https://docs.foursquare.com/fsq-developers-places/reference/usage-guidelines); the linked public page currently gives no substantive retention limits. It also requires branded attribution. The separately documented Personalization API's rules are not evidence of permissions for the new Places endpoint. Confirm the actual Places account terms before choosing any server cache or permanent snapshot retention.

An eventual place stop should retain provider, provider ID, fetched_at, observed_at/date horizon, supplied hours type and attribution. Display “Suggested from <provider>, checked <time>; confirm before going.” This is provider data, not curated editorial or a reservation. Keep unknown hours absent; business-hours evidence must not become a kitchen-open claim. For late dinner, require reported kitchen/dinner service hours covering the planned arrival and intended stay, or return the Maps-search fallback. If nobody supplies suitable hours, offering no named dinner option is the honest result.

## Bounded implementation once sharing policy is chosen

Keep activation disabled by default and require a configured key plus explicit provider selection and call budget. Resolve only near a trusted anchor/origin, request at most one dinner and one drinks candidate group, bound results/timeouts, and never send private user profiles or planning prose to the provider. A missing key, timeout, malformed response, no eligible hours or budget exhaustion should return today's exact Maps-search links. Provider failure must never replace a valid DB-event plan with an invented venue.

Fixture acceptance should cover missing configuration, expired/overnight/exception hours, missing kitchen hours, boundary arrival times, coordinate trust, provider URL allowlisting, attribution, snapshot IDs/fetch timestamps, and repeated public reads under the chosen budget. Live hours/provider/configuration acceptance remains external work. The full ticket is intentionally open until the named-stop and share behavior can satisfy these constraints.

[Public Nominatim policy](https://operations.osmfoundation.org/policies/nominatim/) limits all users of an application together to at most one request per second, requires identifying headers and attribution, and forbids systematic POI extraction. Use a deliberately selected hosted/licensed or self-hosted source for that alternative.
