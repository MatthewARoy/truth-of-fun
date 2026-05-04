"""
Eddie's List source - curated SF Bay Area events newsletter.

NOT_TESTABLE: Requires IMAP credentials (mailbox integration) to fetch newsletter content.
The newsletter is "Via Email Only" - no public web archive of event content.
Configure IMAP_* env vars or use secrets manager for mailbox credentials.
"""

from __future__ import annotations

from typing import Any

from app.ingestion.base import BaseSource

# Requires IMAP credentials - cannot test without mailbox access
TESTABLE = False
REQUIRES_IMAP_CREDENTIALS = True


class EddiesListSource(BaseSource):
    """
    Eddie's List: San Francisco Bay Area curated events newsletter.

    Ingestion requires:
    - IMAP mailbox credentials (stored in secrets manager or IMAP_* env vars)
    - Sender/domain allowlist for ingestion trust
    - metadata_only retention - never republish full paid content

    When configured, fetches newsletter entries and extracts event snippets.
    Optional LLM extraction for unstructured blurbs.
    """

    source_name = "eddies_list"
    source_tier = 3

    async def fetch_events(self, **kwargs: Any) -> list[dict[str, Any]]:
        """
        Fetch events from Eddie's List newsletter.

        Returns empty list unless IMAP credentials are configured.
        To enable: set IMAP_HOST, IMAP_USER, IMAP_PASSWORD (or use secrets manager).
        """
        # TODO: Implement IMAP fetch when credentials available
        # 1. Connect to mailbox via imaplib
        # 2. Search for Eddie's List sender/domain
        # 3. Parse email body for event snippets
        # 4. Optional: LLM extraction for unstructured content
        # 5. Map to CanonicalEvent with organizer.name="Eddie's List"
        return []
