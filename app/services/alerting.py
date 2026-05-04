"""
Operational alerting service.

Sends webhook notifications (Slack/Discord compatible) when:
- A source returns 0 events but historically returned >10
- API key quota is running low
"""

import logging

import httpx

from app.core.config import get_settings

logger = logging.getLogger(__name__)


async def send_alert(*, title: str, message: str, severity: str = "warning") -> None:
    """Send an alert via configured webhook. Fails silently if no webhook configured."""
    settings = get_settings()
    if not settings.alert_webhook_url:
        logger.info("Alert (no webhook): [%s] %s - %s", severity, title, message)
        return

    # Format compatible with both Slack and Discord webhooks
    payload = {
        "text": f"*[{severity.upper()}]* {title}\n{message}",  # Slack format
        "content": f"**[{severity.upper()}]** {title}\n{message}",  # Discord format
    }

    try:
        async with httpx.AsyncClient(timeout=10) as client:
            response = await client.post(settings.alert_webhook_url, json=payload)
            response.raise_for_status()
    except Exception:
        logger.exception("Failed to send alert webhook for: %s", title)
