# Civic and park programming coverage audit (#24)

Recommendation: use one configurable seasonal-series adapter with an official listing feed/detail parser, and a separate calendar/date-aware coverage report. Do not add eleven bespoke scraping classes or synthesize recurring dates from schedules. Retain Funcheap/DoTheBay as useful coverage sources; add official feeds only for demonstrated omissions.

## Evidence boundary

A September 29 read-only audit of the existing local corpus matched 34 historical rows using series names/venue/description. This includes one clearly labeled dev seed, excluded from source evidence. The upcoming/scheduled local cohort has only Ticketmaster, 19hz and Eventbrite, so its missing civic rows cannot distinguish a stale ingestion schedule from a structural connector gap. No deployed feed or live backfill was inspected/changed. The table reports historical representability and official-site status separately.

| Series | Local stored evidence | Official evidence checked | Consequence |
| --- | --- | --- | --- |
| Stern Grove | 11 dated 2026 concerts from sterngrove, plus a dev seed excluded | Existing dedicated source and dated rows | Keep existing connector; validate per-date identity, not one seasonal umbrella row |
| Yerba Buena Gardens Festival | Funcheap and SFStation dated August 15 concert, children's show, plus umbrella rows | [Official site](https://ybgfestival.org/) has upcoming October programs and admission-free season | Existing sources can represent it; compare exact official dates to a fresh crawl before declaring a connector gap |
| Golden Gate Park Band | Three dated August concerts via Funcheap | [Official band site](https://goldengateparkband.org/) describes 2026 season, Sundays April–September and holiday concerts | Seasonal canary must avoid treating winter silence as failure |
| SF Mime Troupe | Two August performances via Funcheap | [Official site](https://www.sfmt.org/) says summer 2026 season has closed | Historical coverage exists; no fabricated future recurrence |
| Sunday Streets | August 23 Bayview rows via Funcheap and DoTheBay | Official page unavailable in this tool during audit | Partial historic evidence; current authoritative schedule remains unverified |
| Jerry Day | No series-name match in local audit | [Official site](https://www.jerryday.org/) dates the 2026 main event to August 1 | Historical candidate omission, not an upcoming alarm |
| Nihonmachi Street Fair | No series-name match | [Official site](https://www.nihonmachistreetfair.org/) marks 2026 over and announces August 7–8, 2027 | Candidate official-source adapter; next-year scope exceeds the current near-term ingest horizon |
| Free museum days | Six YBCA free-admission rows via Funcheap; latest September 9 | [SFMOMA official program reference](https://www.sfmoma.org/press-release/sfmoma-receives-1-5m-grant-from-google-org-in-support-of-major-ruth-asawa-retrospective-premiering-in-san-francisco/) describes resident-restricted First Thursdays | Preserve admission eligibility; verify each future date, hours and reservation rule rather than marking every museum visit free |
| SF Rec & Park programming | One workshop-description/name match; insufficient coverage proof | [Official tentative permit calendar](https://sfrecpark.org/DocumentCenter/View/28453/2026-RPD-Special-Event-Master-Embarcadero) surfaced | A tentative permit spreadsheet is not a confirmed public event feed; official public-calendar fetch timed out |

## Adapter and coverage-check design

A manifest should name the official source URL/domain, supported format (JSON-LD Event, iCalendar or a reviewed site-specific extraction recipe), season/date bounds and known venue mapping. The shared adapter retains only actually published occurrence dates, event-specific URLs, cancellation/estimated-time status and explicit free/admission qualifiers. Apply request/page/result budgets, existing retry/health telemetry and stable provider occurrence identities. Generic season text does not become a repeating weekly series without dated source evidence.

The independent coverage report accepts a bounded set of official occurrence expectations with evidence URLs, expected dates and freshness, and compares those exact title/date/venue identities against the database. States: covered, missing while corpus fresh, corpus stale, expectation stale, and off-season/outside ingest horizon. Generic umbrella rows and dev seeds cannot satisfy a dated occurrence. Missing credentials or an inactive season must remain distinguishable from parse failure. Run on demand first; scheduling or live scraping is not activated here.

Next executable acceptance: a frozen official-page fixture for Yerba Buena and a season-aware expectation fixture, showing separate dates and correct stale/off-season outcomes. Before using the adapter live, validate official current pages, fetch permissions and fresh deployed counts. This audit is progress on #24, not proof of complete civic coverage.
