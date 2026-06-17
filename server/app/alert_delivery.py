from __future__ import annotations

import asyncio
import datetime as dt
import logging
import smtplib
from email.message import EmailMessage

from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from .config import get_settings
from .models import Forecast, SiteAlertDelivery, SiteAlertSettings

settings = get_settings()
logger = logging.getLogger("marketing-analytics.alerts")


async def notify_anomaly_if_needed(
    session: AsyncSession,
    *,
    site_id: str,
    metric: str,
    forecast: Forecast,
) -> None:
    if not forecast.has_anomaly:
        return

    alert_settings = (
        await session.execute(select(SiteAlertSettings).where(SiteAlertSettings.site_id == site_id))
    ).scalar_one_or_none()
    if not alert_settings or not alert_settings.anomaly_alerts_enabled:
        return

    trained_at = forecast.trained_at or dt.datetime.now(dt.timezone.utc)
    if trained_at.tzinfo is None:
        trained_at = trained_at.replace(tzinfo=dt.timezone.utc)
    anomaly_key = f"{metric}:{trained_at.date().isoformat()}"
    message = _build_alert_message(site_id=site_id, metric=metric, forecast=forecast, trained_at=trained_at)

    if alert_settings.slack_enabled and alert_settings.slack_webhook_url:
        await _send_once(
            session,
            site_id=site_id,
            metric=metric,
            channel="slack",
            anomaly_key=anomaly_key,
            send=lambda: _send_slack(alert_settings.slack_webhook_url or "", message),
        )

    recipients = list(alert_settings.email_recipients or [])
    if alert_settings.email_enabled and recipients and settings.alert_email_configured():
        await _send_once(
            session,
            site_id=site_id,
            metric=metric,
            channel="email",
            anomaly_key=anomaly_key,
            send=lambda: _send_email(recipients, site_id, metric, message),
        )


async def _send_once(
    session: AsyncSession,
    *,
    site_id: str,
    metric: str,
    channel: str,
    anomaly_key: str,
    send,
) -> None:
    existing = (
        await session.execute(
            select(SiteAlertDelivery).where(
                SiteAlertDelivery.site_id == site_id,
                SiteAlertDelivery.metric == metric,
                SiteAlertDelivery.channel == channel,
                SiteAlertDelivery.anomaly_key == anomaly_key,
            )
        )
    ).scalar_one_or_none()
    if existing is not None:
        return

    try:
        await send()
    except Exception:
        logger.exception(
            "Failed to send anomaly alert",
            extra={"site_id": site_id, "metric": metric, "channel": channel},
        )
        return

    session.add(
        SiteAlertDelivery(
            site_id=site_id,
            metric=metric,
            channel=channel,
            anomaly_key=anomaly_key,
            sent_at=dt.datetime.now(dt.timezone.utc),
        )
    )
    try:
        await session.commit()
    except IntegrityError:
        await session.rollback()


async def _send_slack(webhook_url: str, message: str) -> None:
    async with AsyncClient(timeout=10.0) as client:
        response = await client.post(webhook_url, json={"text": message})
        response.raise_for_status()


async def _send_email(recipients: list[str], site_id: str, metric: str, message: str) -> None:
    await asyncio.to_thread(_send_email_sync, recipients, site_id, metric, message)


def _send_email_sync(recipients: list[str], site_id: str, metric: str, message: str) -> None:
    if not settings.ALERT_EMAIL_SMTP_HOST or not settings.ALERT_EMAIL_FROM:
        return

    email = EmailMessage()
    email["From"] = settings.ALERT_EMAIL_FROM
    email["To"] = ", ".join(recipients)
    email["Subject"] = f"Valid anomaly alert for {site_id}: {metric}"
    email.set_content(message)

    with smtplib.SMTP(settings.ALERT_EMAIL_SMTP_HOST, settings.ALERT_EMAIL_SMTP_PORT, timeout=10) as smtp:
        if settings.ALERT_EMAIL_USE_TLS:
            smtp.starttls()
        if settings.ALERT_EMAIL_SMTP_USERNAME and settings.ALERT_EMAIL_SMTP_PASSWORD:
            smtp.login(settings.ALERT_EMAIL_SMTP_USERNAME, settings.ALERT_EMAIL_SMTP_PASSWORD)
        smtp.send_message(email)


def _build_alert_message(
    *,
    site_id: str,
    metric: str,
    forecast: Forecast,
    trained_at: dt.datetime,
) -> str:
    return (
        f"Valid anomaly detected for {site_id}: {metric} was unusually different from the site's recent pattern. "
        f"Forecasts may be wider while the trend stabilizes. "
        f"z-score: {forecast.z_score:.2f}. Trained: {trained_at.isoformat()}."
    )
