from __future__ import annotations

import datetime as dt

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..breakdown_logic import normalize_conversion_event
from ..dashboard_auth import _normalize_username, enforce_site_access_with_db, require_dashboard_auth, require_site_owner_with_db
from ..models import SiteGoal, get_session
from ..schemas import SiteGoalResponse, SiteGoalsResponse, SiteGoalUpsertRequest

router = APIRouter(prefix="/site-goals", tags=["settings"])


def _serialize(row: SiteGoal) -> SiteGoalResponse:
    return SiteGoalResponse(
        site_id=row.site_id,
        metric=row.metric,  # type: ignore[arg-type]
        conversion_type=row.conversion_type,
        target=row.target,
        period_days=row.period_days,
        repeat=row.repeat,  # type: ignore[arg-type]
        created_by=row.created_by,
        updated_by=row.updated_by,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


async def _list_goals(session: AsyncSession, site_id: str) -> list[SiteGoal]:
    return (
        await session.execute(
            select(SiteGoal)
            .where(SiteGoal.site_id == site_id)
            .order_by(SiteGoal.metric.asc(), SiteGoal.conversion_type.asc().nullsfirst())
        )
    ).scalars().all()


def _normalize_goal_conversion_type(metric: str, raw_value: str | None) -> str | None:
    if metric != "conversions":
        if raw_value and raw_value.strip():
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="conversion_type can only be set for conversion goals",
            )
        return None
    if raw_value is None or not raw_value.strip():
        return None
    return normalize_conversion_event(raw_value)


def _goal_match(site_id: str, metric: str, conversion_type: str | None):
    filters = [SiteGoal.site_id == site_id, SiteGoal.metric == metric]
    if conversion_type is None:
        filters.append(SiteGoal.conversion_type.is_(None))
    else:
        filters.append(SiteGoal.conversion_type == conversion_type)
    return filters


@router.get("", response_model=SiteGoalsResponse)
async def list_site_goals(
    site_id: str,
    claims: dict | None = Depends(require_dashboard_auth),
    session: AsyncSession = Depends(get_session),
) -> SiteGoalsResponse:
    await enforce_site_access_with_db(site_id=site_id, claims=claims, session=session)
    rows = await _list_goals(session, site_id)
    return SiteGoalsResponse(site_id=site_id, goals=[_serialize(row) for row in rows])


@router.put("", response_model=SiteGoalsResponse)
async def upsert_site_goal(
    payload: SiteGoalUpsertRequest,
    claims: dict | None = Depends(require_dashboard_auth),
    session: AsyncSession = Depends(get_session),
) -> SiteGoalsResponse:
    await require_site_owner_with_db(site_id=payload.site_id, claims=claims, session=session)
    username = _normalize_username(claims.get("sub") if isinstance(claims, dict) else None)
    now = dt.datetime.now(dt.timezone.utc)
    conversion_type = _normalize_goal_conversion_type(payload.metric, payload.conversion_type)
    existing = (
        await session.execute(
            select(SiteGoal).where(
                *_goal_match(payload.site_id, payload.metric, conversion_type),
            )
        )
    ).scalar_one_or_none()
    if existing:
        existing.target = payload.target
        existing.period_days = payload.period_days
        existing.repeat = payload.repeat
        existing.updated_by = username
        existing.updated_at = now
    else:
        session.add(
            SiteGoal(
                site_id=payload.site_id,
                metric=payload.metric,
                conversion_type=conversion_type,
                target=payload.target,
                period_days=payload.period_days,
                repeat=payload.repeat,
                created_by=username,
                updated_by=username,
                created_at=now,
                updated_at=now,
            )
        )
    await session.commit()
    rows = await _list_goals(session, payload.site_id)
    return SiteGoalsResponse(site_id=payload.site_id, goals=[_serialize(row) for row in rows])


@router.delete("/{metric}", response_model=SiteGoalsResponse)
async def delete_site_goal(
    metric: str,
    site_id: str,
    conversion_type: str | None = None,
    claims: dict | None = Depends(require_dashboard_auth),
    session: AsyncSession = Depends(get_session),
) -> SiteGoalsResponse:
    await require_site_owner_with_db(site_id=site_id, claims=claims, session=session)
    if metric not in {"revenue", "conversions", "pageviews", "sessions", "uniques"}:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Goal not found")
    normalized_conversion_type = _normalize_goal_conversion_type(metric, conversion_type)
    existing = (
        await session.execute(
            select(SiteGoal).where(
                *_goal_match(site_id, metric, normalized_conversion_type),
            )
        )
    ).scalar_one_or_none()
    if existing:
        await session.delete(existing)
        await session.commit()
    rows = await _list_goals(session, site_id)
    return SiteGoalsResponse(site_id=site_id, goals=[_serialize(row) for row in rows])
