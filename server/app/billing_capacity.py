"""Advisory usage and a durable, manually reviewed capacity-request workflow."""
from __future__ import annotations

import datetime as dt
import uuid

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from .access_control import require_admin_api_token
from .dashboard_auth import require_dashboard_auth, require_site_owner_with_db
from .entitlements import (
    ACTIVE_SUBSCRIPTION_STATUSES, PAGEVIEW_CAPACITY_BLOCK, PAGEVIEW_CAPACITY_PRICE_USD,
    SOLO_MONTHLY_PAGEVIEWS, STANDARD_MONTHLY_PAGEVIEWS, effective_plan_for_record, account_subscription,
)
from .models import CapacityRequest, DashboardSite, SitePlan, get_session
from .ops_alerts import notify_ops_alert
from .schemas import CapacityRequestPayload, CapacityRequestResolution
from .usage_accounting import utc

router = APIRouter(tags=["billing"])


async def account_billing_record(session: AsyncSession, site: DashboardSite):
    return await account_subscription(session, site.owner_username)


def capacity_policy(record: SitePlan | None, fallback: SitePlan | None, ambiguous: bool) -> dict:
    plan = effective_plan_for_record(record or fallback)
    blocks = max(0, record.extra_pageview_quantity or 0) if record and plan == "standard" else 0
    included = None if ambiguous or plan == "pro" else (
        STANDARD_MONTHLY_PAGEVIEWS if plan == "standard" else SOLO_MONTHLY_PAGEVIEWS
    )
    return {
        "plan": plan, "included_pageviews": included,
        "purchased_additional_millions": blocks,
        "total_pageview_capacity": included + blocks * PAGEVIEW_CAPACITY_BLOCK if included is not None else None,
        "additional_million_price_usd": PAGEVIEW_CAPACITY_PRICE_USD,
        "ambiguous_subscriptions": ambiguous,
        "can_request_capacity": bool(record and not ambiguous and plan == "standard"
                                     and record.stripe_subscription_status in ACTIVE_SUBSCRIPTION_STATUSES
                                     and not record.stripe_cancel_at_period_end),
        "enforcement": "advisory", "automatic_billing": False,
    }


def request_summary(row: CapacityRequest | None):
    if row is None:
        return None
    return {"request_id": row.request_id, "site_id": row.site_id,
            "additional_millions": row.additional_millions, "monthly_price_usd": row.monthly_price_usd,
            "status": row.status, "created_at": utc(row.created_at),
            "resolved_at": utc(row.resolved_at) if row.resolved_at else None}


async def pending_capacity_request(session: AsyncSession, account_key: str):
    return (await session.execute(select(CapacityRequest).where(
        CapacityRequest.account_key == account_key, CapacityRequest.status == "pending",
    ))).scalar_one_or_none()


@router.post("/billing/capacity-request")
async def request_capacity(
    payload: CapacityRequestPayload,
    background_tasks: BackgroundTasks,
    auth_claims: dict | None = Depends(require_dashboard_auth),
    session: AsyncSession = Depends(get_session),
):
    site = await require_site_owner_with_db(site_id=payload.site_id, claims=auth_claims, session=session)
    record, ambiguous = await account_billing_record(session, site)
    if not capacity_policy(record, None, ambiguous)["can_request_capacity"]:
        raise HTTPException(409, "Capacity requests require one active Standard subscription for this owner")
    account_key = f"owner:{site.owner_username}"
    existing = await pending_capacity_request(session, account_key)
    if existing:
        if existing.additional_millions != payload.additional_millions:
            raise HTTPException(409, "A capacity request is already awaiting review")
        return request_summary(existing)
    row = CapacityRequest(
        request_id=str(uuid.uuid4()), account_key=account_key, site_id=site.site_id,
        subscription_id=record.stripe_subscription_id, additional_millions=payload.additional_millions,
        monthly_price_usd=payload.additional_millions * PAGEVIEW_CAPACITY_PRICE_USD, status="pending",
    )
    session.add(row)
    try:
        await session.commit()
    except IntegrityError:
        await session.rollback()
        existing = await pending_capacity_request(session, account_key)
        if existing and existing.additional_millions == payload.additional_millions:
            return request_summary(existing)
        raise HTTPException(409, "A capacity request is already awaiting review") from None
    background_tasks.add_task(
        notify_ops_alert, source="billing_capacity_request", severity="info",
        message="An owner requested additional monthly capacity. Review and obtain approval before billing.",
        metadata={"request_id": row.request_id, "site_id": site.site_id,
                  "additional_millions": row.additional_millions, "monthly_price_usd": row.monthly_price_usd},
    )
    return request_summary(row)


@router.get("/admin/billing/capacity-requests", dependencies=[Depends(require_admin_api_token)])
async def list_capacity_requests(session: AsyncSession = Depends(get_session)):
    rows = (await session.execute(select(CapacityRequest).where(
        CapacityRequest.status == "pending",
    ).order_by(CapacityRequest.created_at).limit(100))).scalars().all()
    return [{**request_summary(row), "subscription_id": row.subscription_id} for row in rows]


@router.post("/admin/billing/capacity-requests/resolve", dependencies=[Depends(require_admin_api_token)])
async def resolve_capacity_request(payload: CapacityRequestResolution, session: AsyncSession = Depends(get_session)):
    row = await session.get(CapacityRequest, payload.request_id)
    if row is None:
        raise HTTPException(404, "Capacity request not found")
    if row.status != "pending" and row.status != payload.status:
        raise HTTPException(409, "Capacity request was already resolved")
    if row.status == "pending":
        row.status = payload.status
        row.resolved_at = dt.datetime.now(dt.timezone.utc)
        await session.commit()
    # This is an administrative acknowledgement, never a Stripe mutation or entitlement grant.
    return request_summary(row)
