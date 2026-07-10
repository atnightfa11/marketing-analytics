from __future__ import annotations

import asyncio
import datetime as dt
import json
import logging
import smtplib
from email.message import EmailMessage
from typing import Any

from httpx import AsyncClient

from .config import get_settings
from .schemas import AlertWebhookPayload

settings = get_settings()
logger = logging.getLogger("marketing-analytics.ops-alerts")
_last_sent_at: dict[str, dt.datetime] = {}


async def notify_ops_alert(
    *,
    source: str,
    severity: str,
    message: str,
    metadata: dict[str, Any] | None = None,
) -> None:
    payload = AlertWebhookPayload(
        source=source,
        severity=_normalize_severity(severity),
        message=message,
        metadata=metadata or {},
    )
    if _is_deduped(payload):
        return

    deliveries = []
    if settings.OPS_ALERT_WEBHOOK_URL:
        deliveries.append(_send_webhook(payload))
    recipients = settings.ops_alert_email_recipients()
    if recipients and settings.alert_email_configured():
        deliveries.append(_send_email(recipients, payload))

    if not deliveries:
        logger.warning(
            "Ops alert generated but no ops alert destination is configured",
            extra={"source": payload.source, "severity": payload.severity, "message": payload.message},
        )
        return

    results = await asyncio.gather(*deliveries, return_exceptions=True)
    for result in results:
        if isinstance(result, Exception):
            logger.error(
                "Ops alert delivery failed",
                extra={
                    "source": payload.source,
                    "severity": payload.severity,
                    "error": str(result),
                },
            )


async def deliver_ops_alert_payload(payload: AlertWebhookPayload) -> None:
    await notify_ops_alert(
        source=payload.source,
        severity=payload.severity,
        message=payload.message,
        metadata=payload.metadata,
    )


def _normalize_severity(value: str) -> str:
    normalized = value.strip().lower()
    if normalized in {"info", "warning", "critical"}:
        return normalized
    return "critical"


def _is_deduped(payload: AlertWebhookPayload) -> bool:
    window_seconds = max(0, settings.OPS_ALERT_DEDUP_SECONDS)
    if window_seconds == 0:
        return False

    key = json.dumps(
        {
            "source": payload.source,
            "severity": payload.severity,
            "message": payload.message,
            "metadata": payload.metadata,
        },
        sort_keys=True,
        default=str,
    )
    now = dt.datetime.now(dt.timezone.utc)
    last_sent_at = _last_sent_at.get(key)
    if last_sent_at and (now - last_sent_at).total_seconds() < window_seconds:
        return True
    _last_sent_at[key] = now
    return False


async def _send_webhook(payload: AlertWebhookPayload) -> None:
    assert settings.OPS_ALERT_WEBHOOK_URL
    async with AsyncClient(timeout=10.0) as client:
        response = await client.post(
            settings.OPS_ALERT_WEBHOOK_URL,
            json={
                "text": _plain_text(payload),
                "source": payload.source,
                "severity": payload.severity,
                "message": payload.message,
                "metadata": payload.metadata,
            },
        )
        response.raise_for_status()


async def _send_email(recipients: list[str], payload: AlertWebhookPayload) -> None:
    await asyncio.to_thread(_send_email_sync, recipients, payload)


def _send_email_sync(recipients: list[str], payload: AlertWebhookPayload) -> None:
    if not settings.ALERT_EMAIL_SMTP_HOST or not settings.ALERT_EMAIL_FROM:
        return

    email = EmailMessage()
    email["From"] = settings.ALERT_EMAIL_FROM
    email["To"] = ", ".join(recipients)
    email["Subject"] = f"[Valid ops] {payload.severity.upper()}: {payload.source}"
    email.set_content(_plain_text(payload))

    with smtplib.SMTP(settings.ALERT_EMAIL_SMTP_HOST, settings.ALERT_EMAIL_SMTP_PORT, timeout=10) as smtp:
        if settings.ALERT_EMAIL_USE_TLS:
            smtp.starttls()
        if settings.ALERT_EMAIL_SMTP_USERNAME and settings.ALERT_EMAIL_SMTP_PASSWORD:
            smtp.login(settings.ALERT_EMAIL_SMTP_USERNAME, settings.ALERT_EMAIL_SMTP_PASSWORD)
        smtp.send_message(email)


def _plain_text(payload: AlertWebhookPayload) -> str:
    metadata = json.dumps(payload.metadata, indent=2, sort_keys=True, default=str)
    return (
        f"[{payload.severity.upper()}] {payload.message}\n"
        f"Source: {payload.source}\n"
        f"Metadata:\n{metadata}"
    )
