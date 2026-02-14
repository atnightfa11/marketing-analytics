from __future__ import annotations

import csv
import datetime as dt
import io

from fastapi import APIRouter, Depends, Header, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import RawReport, SitePlan, get_session
from .shuffle import decode_token, resolve_plan, validate_token
from ..scheduler.nightly_reduce import reduce_reports
from ..scheduler.prophet_job import train_prophet
from ..schemas import HistoricalCsvImportRequest, HistoricalImportRequest, HistoricalImportResponse

router = APIRouter(tags=["imports"])


async def _authorize_import(site_id: str, import_token: str | None, session: AsyncSession) -> str:
    if not import_token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Missing import token")
    claims = decode_token(import_token)
    await validate_token(claims, import_token, session)
    if claims.site_id != site_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Token site mismatch")
    return await resolve_plan(site_id, claims.plan, session)


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
    x_upload_token: str | None = Header(default=None, alias="X-Upload-Token"),
    session: AsyncSession = Depends(get_session),
):
    plan_record = await session.get(SitePlan, payload.site_id)
    target_plan = plan_record.plan if plan_record else "free"
    if target_plan == "pro":
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Pro imports are not supported")
    await _authorize_import(payload.site_id, x_upload_token, session)
    return await _import_rows(payload, session, target_plan=target_plan)


@router.post("/import/historical-csv", response_model=HistoricalImportResponse)
async def import_historical_csv(
    payload: HistoricalCsvImportRequest,
    x_upload_token: str | None = Header(default=None, alias="X-Upload-Token"),
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
    plan_record = await session.get(SitePlan, payload.site_id)
    target_plan = plan_record.plan if plan_record else "free"
    if target_plan == "pro":
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Pro imports are not supported")
    await _authorize_import(payload.site_id, x_upload_token, session)
    return await _import_rows(parsed_payload, session, target_plan=target_plan)
