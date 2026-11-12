"""Transactional email over SMTP (password resets).

Deliberately small: one provider-agnostic SMTP path, because every email
service (SES, Postmark, Mailgun, Resend, a Workspace relay) speaks it.
"""

from __future__ import annotations

import logging
import smtplib
import ssl
from email.message import EmailMessage

from app.core.config import Settings, get_settings

logger = logging.getLogger(__name__)


def email_is_configured(settings: Settings | None = None) -> bool:
    settings = settings or get_settings()
    return bool(settings.smtp_host and settings.smtp_from)


def send_email(*, to: str, subject: str, body: str, settings: Settings | None = None) -> bool:
    """Send a plain-text message. Returns whether it was handed to the server.

    Never raises: a mail outage must not turn "forgot my password" into a 500,
    and must not reveal (by failing differently) whether an account exists.
    """
    settings = settings or get_settings()
    if not email_is_configured(settings):
        logger.warning("Email not sent (%s): SMTP_HOST / SMTP_FROM are not configured.", subject)
        return False

    message = EmailMessage()
    message["From"] = settings.smtp_from
    message["To"] = to
    message["Subject"] = subject
    message.set_content(body)
    try:
        with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=10) as client:
            if settings.smtp_starttls:
                client.starttls(context=ssl.create_default_context())
            if settings.smtp_username:
                client.login(settings.smtp_username, settings.smtp_password or "")
            client.send_message(message)
        return True
    except Exception:
        # The recipient address is PII; the exception type is enough to act on.
        logger.exception("Email delivery failed (%s).", subject)
        return False
