from __future__ import annotations

import csv
import datetime as dt
import io

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
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

    rows_by_key = {}
    for row in payload.rows:
        key = (row.day, row.metric)
        if key in rows_by_key:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Duplicate import row for {row.day.isoformat()} {row.metric}",
            )
        rows_by_key[key] = row

    inserted = 0
    touched_days = {day for day, _metric in rows_by_key}
    touched_metrics = {metric for _day, metric in rows_by_key}
    if touched_days:
        existing_reports = (
            await session.execute(
                select(RawReport)
                .where(
                    RawReport.site_id == payload.site_id,
                    RawReport.day >= min(touched_days),
                    RawReport.day <= max(touched_days),
                    RawReport.kind.in_(touched_metrics),
                )
                .order_by(RawReport.day, RawReport.kind, RawReport.id)
            )
        ).scalars().all()

        live_overlap: set[tuple[dt.date, str]] = set()
        historical_reports_to_replace: list[RawReport] = []
        for report in existing_reports:
            key = (report.day, report.kind)
            if key not in rows_by_key:
                continue
            report_payload = report.payload if isinstance(report.payload, dict) else {}
            if report_payload.get("historical_import"):
                historical_reports_to_replace.append(report)
            else:
                live_overlap.add(key)

        if live_overlap and not payload.allow_live_overlap:
            overlap_preview = ", ".join(
                f"{day.isoformat()} {metric}" for day, metric in sorted(live_overlap)[:8]
            )
            suffix = "" if len(live_overlap) <= 8 else f", and {len(live_overlap) - 8} more"
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=(
                    "Import overlaps existing Valid-collected data. "
                    f"Remove those dates from the CSV or re-run with overlap explicitly allowed. Overlap: {overlap_preview}{suffix}"
                ),
            )

        for report in historical_reports_to_replace:
            await session.delete(report)

    for row in rows_by_key.values():
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

    parsed_payload = HistoricalImportRequest(
        site_id=payload.site_id,
        rows=rows,
        allow_live_overlap=payload.allow_live_overlap,
    )
    target_plan = await _require_standard_import_access(payload.site_id, auth_claims, session)
    return await _import_rows(parsed_payload, session, target_plan=target_plan)
