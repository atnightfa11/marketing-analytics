from __future__ import annotations

import datetime as dt
import re
from urllib.parse import urlparse

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import get_settings
from ..dashboard_auth import enforce_site_access_with_db, require_dashboard_auth, require_site_owner_with_db
from ..entitlements import require_anomaly_alerts
from ..models import SiteAlertSettings, SitePlan, get_session
from ..schemas import SiteAlertSettingsResponse, SiteAlertSettingsUpdateRequest

router = APIRouter(prefix="/site-alerts", tags=["settings"])
settings = get_settings()

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
MAX_EMAIL_RECIPIENTS = 10


def _normalize_recipients(values: list[str]) -> list[str]:
    recipients: list[str] = []
    seen: set[str] = set()
    for value in values:
        for part in re.split(r"[\n,;]+", value):
            email = part.strip().lower()
            if not email:
                continue
            if not EMAIL_RE.match(email):
                raise HTTPException(status_code=400, detail=f"Invalid email recipient: {part.strip()}")
            if email not in seen:
                seen.add(email)
                recipients.append(email)
    if len(recipients) > MAX_EMAIL_RECIPIENTS:
        raise HTTPException(status_code=400, detail=f"Use {MAX_EMAIL_RECIPIENTS} or fewer email recipients")
    return recipients


def _normalize_slack_webhook(value: str | None) -> str | None:
    if value is None:
        return None
    cleaned = value.strip()
    if not cleaned:
        return ""
    parsed = urlparse(cleaned)
    if parsed.scheme != "https" or parsed.netloc != "hooks.slack.com":
        raise HTTPException(status_code=400, detail="Enter a valid Slack incoming webhook URL")
    if not parsed.path.startswith("/services/"):
        raise HTTPException(status_code=400, detail="Enter a valid Slack incoming webhook URL")
    return cleaned


def _serialize(row: SiteAlertSettings | None, site_id: str) -> SiteAlertSettingsResponse:
    return SiteAlertSettingsResponse(
        site_id=site_id,
        anomaly_alerts_enabled=bool(row.anomaly_alerts_enabled) if row else False,
        slack_enabled=bool(row.slack_enabled) if row else False,
        slack_webhook_url_set=bool(row and row.slack_webhook_url),
        email_enabled=bool(row.email_enabled) if row else False,
        email_recipients=list(row.email_recipients or []) if row else [],
        email_delivery_configured=settings.alert_email_configured(),
        updated_at=row.updated_at if row else None,
    )


async def _get_settings_row(session: AsyncSession, site_id: str) -> SiteAlertSettings | None:
    return (
        await session.execute(select(SiteAlertSettings).where(SiteAlertSettings.site_id == site_id))
    ).scalar_one_or_none()


async def _require_standard_alert_access(session: AsyncSession, site_id: str) -> None:
    plan_record = await session.get(SitePlan, site_id)
    require_anomaly_alerts(plan_record.plan if plan_record else "free")


@router.get("", response_model=SiteAlertSettingsResponse, dependencies=[Depends(require_dashboard_auth)])
async def get_site_alert_settings(
    site_id: str,
    claims: dict | None = Depends(require_dashboard_auth),
    session: AsyncSession = Depends(get_session),
) -> SiteAlertSettingsResponse:
    await enforce_site_access_with_db(site_id=site_id, claims=claims, session=session)
    await _require_standard_alert_access(session, site_id)
    row = await _get_settings_row(session, site_id)
    return _serialize(row, site_id)


@router.put("", response_model=SiteAlertSettingsResponse, dependencies=[Depends(require_dashboard_auth)])
async def update_site_alert_settings(
    payload: SiteAlertSettingsUpdateRequest,
    claims: dict | None = Depends(require_dashboard_auth),
    session: AsyncSession = Depends(get_session),
) -> SiteAlertSettingsResponse:
    await require_site_owner_with_db(site_id=payload.site_id, claims=claims, session=session)
    await _require_standard_alert_access(session, payload.site_id)

    recipients = _normalize_recipients(payload.email_recipients)
    webhook_in_payload = "slack_webhook_url" in payload.model_fields_set
    normalized_webhook = _normalize_slack_webhook(payload.slack_webhook_url) if webhook_in_payload else None

    row = await _get_settings_row(session, payload.site_id)
    username = claims.get("sub") if isinstance(claims, dict) else None
    now = dt.datetime.now(dt.timezone.utc)
    if row is None:
        row = SiteAlertSettings(
            site_id=payload.site_id,
            created_by=username.strip().lower() if isinstance(username, str) and username.strip() else None,
            created_at=now,
        )
        session.add(row)

    if webhook_in_payload:
        row.slack_webhook_url = normalized_webhook or None

    if payload.slack_enabled and not row.slack_webhook_url:
        raise HTTPException(status_code=400, detail="Slack alerts need a Slack incoming webhook URL")
    if payload.email_enabled and not recipients:
        raise HTTPException(status_code=400, detail="Email alerts need at least one recipient")
    if payload.anomaly_alerts_enabled and not payload.slack_enabled and not payload.email_enabled:
        raise HTTPException(status_code=400, detail="Enable Slack or email before turning on anomaly alerts")

    row.anomaly_alerts_enabled = payload.anomaly_alerts_enabled
    row.slack_enabled = payload.slack_enabled
    row.email_enabled = payload.email_enabled
    row.email_recipients = recipients
    row.updated_by = username.strip().lower() if isinstance(username, str) and username.strip() else None
    row.updated_at = now

    await session.commit()
    await session.refresh(row)
    return _serialize(row, payload.site_id)
