"""Transactional text email using the existing SMTP configuration."""
import asyncio
import smtplib
import ssl
from email.message import EmailMessage

from .config import get_settings


def _send(recipients: list[str], subject: str, body: str):
    settings = get_settings()
    if not settings.alert_email_configured():
        raise RuntimeError("SMTP is not configured")
    message = EmailMessage()
    message["From"] = settings.ALERT_EMAIL_FROM
    message["To"] = ", ".join(recipients)
    message["Subject"] = subject
    message.set_content(body)
    with smtplib.SMTP(
        settings.ALERT_EMAIL_SMTP_HOST, settings.ALERT_EMAIL_SMTP_PORT, timeout=15
    ) as smtp:
        if settings.ALERT_EMAIL_USE_TLS:
            smtp.starttls(context=ssl.create_default_context())
        if settings.ALERT_EMAIL_SMTP_USERNAME and settings.ALERT_EMAIL_SMTP_PASSWORD:
            smtp.login(
                settings.ALERT_EMAIL_SMTP_USERNAME, settings.ALERT_EMAIL_SMTP_PASSWORD
            )
        smtp.send_message(message)


async def send_email(recipients: list[str], subject: str, body: str):
    await asyncio.to_thread(_send, recipients, subject, body)
