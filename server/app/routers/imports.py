from __future__ import annotations

import csv
import datetime as dt
import io

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import RawReport, SitePlan, get_session
from ..dashboard_auth import enforce_site_access_with_db, require_dashboard_auth
from ..scheduler.nightly_reduce import reduce_reports
from ..scheduler.prophet_job import train_prophet
from ..schemas import HistoricalCsvImportRequest, HistoricalImportRequest, HistoricalImportResponse

router = APIRouter(tags=["imports"])


async def _require_standard_import_access(
    site_id: str,
    claims: dict | None,
    session: AsyncSession,
) -> str:
    await enforce_site_access_with_db(site_id=site_id, claims=claims, session=session)
    plan_record = await session.get(SitePlan, site_id)
    target_plan = plan_record.plan if plan_record else "free"
    if target_plan != "standard":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Historical imports require the Standard plan",
        )
    return target_plan


async def _import_rows(
    payload: HistoricalImportRequest,
    session: AsyncSession,
    target_plan: str,
) -> HistoricalImportResponse:
    if target_plan == "pro":
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Pro imports are not supported")

    inserted = 0
    touched_days: set[dt.date] = set()
    for row in payload.rows:
        touched_days.add(row.day)
        session.add(
            RawReport(
                site_id=payload.site_id,
                kind=row.metric,
                day=row.day,
                payload={"historical_import": True, "value": row.value},
                epsilon_used=0.0,
                sampling_rate=1.0,
                server_received_at=dt.datetime.combine(row.day, dt.time(12, 0), tzinfo=dt.timezone.utc),
            )
        )
        inserted += 1
    await session.commit()

    if touched_days:
        start_day = min(touched_days)
        end_day = max(touched_days)
        await reduce_reports(session, start_day=start_day, end_day=end_day)
        for metric in ["pageviews", "sessions", "uniques", "conversions", "revenue"]:
            await train_prophet(session, site_id=payload.site_id, metric=metric, plan=target_plan)

    return HistoricalImportResponse(site_id=payload.site_id, imported_rows=inserted, reduced_days=len(touched_days))


@router.post("/import/historical", response_model=HistoricalImportResponse)
async def import_historical(
    payload: HistoricalImportRequest,
    auth_claims: dict | None = Depends(require_dashboard_auth),
    session: AsyncSession = Depends(get_session),
):
    target_plan = await _require_standard_import_access(payload.site_id, auth_claims, session)
    return await _import_rows(payload, session, target_plan=target_plan)


@router.post("/import/historical-csv", response_model=HistoricalImportResponse)
async def import_historical_csv(
    payload: HistoricalCsvImportRequest,
    auth_claims: dict | None = Depends(require_dashboard_auth),
    session: AsyncSession = Depends(get_session),
):
    content = payload.csv_text
    reader = csv.DictReader(io.StringIO(content))
    rows = []
    for idx, row in enumerate(reader, start=2):
        try:
            day = dt.date.fromisoformat(str(row.get("day", "")).strip())
            metric = str(row.get("metric", "")).strip()
            value = float(row.get("value", 0.0))
            if metric not in {"uniques", "pageviews", "sessions", "conversions", "revenue"}:
                raise ValueError("invalid metric")
            if value < 0:
                raise ValueError("value must be non-negative")
            rows.append({"day": day, "metric": metric, "value": value})
        except Exception as exc:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Invalid CSV row {idx}: {exc}",
            ) from exc

    parsed_payload = HistoricalImportRequest(site_id=payload.site_id, rows=rows)
    target_plan = await _require_standard_import_access(payload.site_id, auth_claims, session)
    return await _import_rows(parsed_payload, session, target_plan=target_plan)
