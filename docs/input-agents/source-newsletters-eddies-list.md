# Input Agent Spec: Newsletters (Eddie's List)

## Source Summary
- Source ID: `eddies_list`
- Type: Subscription ingest (email/web) + extraction
- Strategic role: trusted curated picks and high-signal local recommendations

## Access and Accounts
- Account type: mailbox integration (IMAP/forwarder) and optional paid subscription account
- Credential handling:
  - mailbox creds stored in secrets manager
  - sender/domain allowlist for ingestion trust
- Ethical/legal posture: metadata extraction and deep-linking only

## Ingestion Strategy
- Fetch newsletter entries from email or permitted web copies
- Parse sections/items into candidate event snippets
- Optional LLM extraction for unstructured blurbs
- Store only search metadata required for discovery and attribution

## Field Mapping
- item headline -> `title`
- mentioned venue/date -> `location.*`, `start_time`
- source issue URL/substack URL -> `source.source_url`
- curator attribution -> `organizer.name=Eddie's List`

## Quality and Risk Controls
- retention policy: `metadata_only`
- never republish full paid content body
- include explicit source attribution and outbound links

## Operational Metrics
- issues processed count
- extracted event count per issue
- compliance audit pass rate (metadata-only enforcement)
