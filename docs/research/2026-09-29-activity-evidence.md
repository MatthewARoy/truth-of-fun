# Activity balance: corpus evidence before a feature (#15)

Recommendation: do not add a health or creativity score to the recommender from the current listings. First improve descriptive coverage, then validate an opt-in description of opportunities against actual participant roles. This completes the suggested initial measurement; audience, dimensions and product behavior remain deliberate design work.

## Read-only measurement

At 2026-09-30 00:09 UTC (September 29 Pacific), the existing local corpus held 3,130 events, 1,455 scheduled and 712 upcoming/scheduled. Of the upcoming cohort, 286 had a nonempty description (40.2%) and 240 had at least 80 description characters (33.7%). Source composition was 268 19hz, 438 Ticketmaster and 6 Eventbrite. Those numbers describe this local database snapshot, including older ingestion, rather than the deployed feed or future source coverage.

A reproducible 40-row sample ordered by `md5(id::text || ':activity-diet-20260929')` was inspected using title and at most 1,200 description characters. Fifteen had descriptions. One supplied direct evidence of an available movement opportunity: a dance floor. Thirty-nine lacked sufficient evidence for any of the screened participation dimensions. This 1/40 (2.5%) is a conservative screening result, not a calibrated corpus estimate or an effect score.

Screened dimensions: movement, participatory creativity, exchange of ideas, restoration and personal novelty. Values are nullable evidence indicators, not a prescribed adult framework. An available dance floor supports movement opportunity; it does not establish that a guest will dance or benefit. Unsupported values remain null. Every result records a listing ID/source URL, reviewed-input hash and a short inspection reason. The complete 40-row evidence record is saved with the session outputs.

Inspection exposed three important failure modes:

- Long Ticketmaster descriptions often describe entry rules and ticket policies. Text length is not evidence quality.
- A theatrical production describes the performance, but does not establish audience collaboration, exploration or participation.
- Charitable mental-health donations do not make an event restorative. An open-mic title suggests a format but does not establish this user's role, access or facilitator behavior.

## Framework boundary and next experiment

[Bay Area Discovery Museum's CREATE framework](https://bayareadiscoverymuseum.org/wp-content/uploads/2024/09/Create_Framework_OUTLINED_Lo-Rez.pdf) addresses educator-designed experiences for children in their first decade and families. Its dimensional shape is useful; this predominantly adult/nightlife sample does not validate transplanting its labels or outcome claims. No paid model was used and no recommendation, profile or objective was changed.

For a family pilot, sample listings explicitly intended for children and inspect facilitator/participation evidence before applying CREATE language, with attribution. For adults, begin with user-selected activity goals and an inspectable distribution of observed activities. Novelty requires that person's history; restoration requires their feedback, not event marketing. Proposed future records should retain input hashes, source facts, inference method/version, time, nullable confidence and corrections. Cadence reflects confirmed or user-reported participation, not clicks or saved events.

Next deliverable: a stratified sample across family, workshops, active/outdoor and performance listings, with independent human inspection and a held-out agreement check. This sample is too small and source-concentrated to justify product-wide scoring. User-set goals and reviewable observations can be designed now; automatic prescription of a healthy mix remains unsupported.
