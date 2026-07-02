from __future__ import annotations

import csv
import datetime as dt
import io

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..dashboard_auth import _normalize_username, enforce_site_access_with_db, require_dashboard_auth
from ..entitlements import require_historical_imports
from ..models import HistoricalImportBatch, RawReport, SitePlan, get_session
from ..scheduler.nightly_reduce import reduce_reports
from ..scheduler.prophet_job import refresh_site_metric_forecast
from ..schemas import (
    HistoricalCsvImportRequest,
    HistoricalImportBatchResponse,
    HistoricalImportHistoryResponse,
    HistoricalImportPreviewOverlap,
    HistoricalImportPreviewResponse,
    HistoricalImportRequest,
    HistoricalImportRow,
    HistoricalImportResponse,
    HistoricalImportRollbackResponse,
)

router = APIRouter(tags=["imports"])


async def _require_standard_import_access(
    site_id: str,
    claims: dict | None,
    session: AsyncSession,
) -> str:
    await enforce_site_access_with_db(site_id=site_id, claims=claims, session=session)
    plan_record = await session.get(SitePlan, site_id)
    target_plan = plan_record.plan if plan_record else "free"
    require_historical_imports(target_plan)
    return target_plan


def _parse_historical_csv(content: str) -> tuple[list[HistoricalImportRow], list[str]]:
    reader = csv.DictReader(io.StringIO(content))
    rows: list[HistoricalImportRow] = []
    errors: list[str] = []
    if not reader.fieldnames:
        return rows, ["CSV must include a header row with day, metric, value."]

    required = {"day", "metric", "value"}
    normalized_fields = {field.strip() for field in reader.fieldnames if field}
    missing = sorted(required - normalized_fields)
    if missing:
        return rows, [f"CSV is missing required column(s): {', '.join(missing)}."]

    seen: set[tuple[dt.date, str]] = set()
    for idx, row in enumerate(reader, start=2):
        try:
            day = dt.date.fromisoformat(str(row.get("day", "")).strip())
            metric = str(row.get("metric", "")).strip()
            value = float(row.get("value", 0.0))
            if metric not in {"uniques", "pageviews", "sessions", "conversions", "revenue"}:
                raise ValueError("invalid metric")
            if value < 0:
                raise ValueError("value must be non-negative")
            key = (day, metric)
            if key in seen:
                errors.append(f"Duplicate import row for {day.isoformat()} {metric}.")
                continue
            seen.add(key)
            rows.append(HistoricalImportRow(day=day, metric=metric, value=value))
        except Exception as exc:
            errors.append(f"Invalid CSV row {idx}: {exc}")
    return rows, errors


async def _find_existing_import_overlaps(
    *,
    session: AsyncSession,
    site_id: str,
    rows_by_key: dict[tuple[dt.date, str], HistoricalImportRow],
) -> tuple[list[HistoricalImportPreviewOverlap], list[HistoricalImportPreviewOverlap]]:
    if not rows_by_key:
        return [], []

    touched_days = {day for day, _metric in rows_by_key}
    touched_metrics = {metric for _day, metric in rows_by_key}
    existing_reports = (
        await session.execute(
            select(RawReport)
            .where(
                RawReport.site_id == site_id,
                RawReport.day >= min(touched_days),
                RawReport.day <= max(touched_days),
                RawReport.kind.in_(touched_metrics),
            )
            .order_by(RawReport.day, RawReport.kind, RawReport.id)
        )
    ).scalars().all()

    live_counts: dict[tuple[dt.date, str], int] = {}
    historical_counts: dict[tuple[dt.date, str], int] = {}
    for report in existing_reports:
        key = (report.day, report.kind)
        if key not in rows_by_key:
            continue
        report_payload = report.payload if isinstance(report.payload, dict) else {}
        target = historical_counts if report_payload.get("historical_import") else live_counts
        target[key] = target.get(key, 0) + 1

    def serialize(counts: dict[tuple[dt.date, str], int], source: str) -> list[HistoricalImportPreviewOverlap]:
        return [
            HistoricalImportPreviewOverlap(day=day, metric=metric, source=source, count=count)
            for (day, metric), count in sorted(counts.items())
        ]

    return serialize(live_counts, "live"), serialize(historical_counts, "historical_import")


async def _import_rows(
    payload: HistoricalImportRequest,
    session: AsyncSession,
    target_plan: str,
    claims: dict | None,
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
    if not touched_days:
        return HistoricalImportResponse(site_id=payload.site_id, imported_rows=0, reduced_days=0, batch_id=None)

    if touched_days:
        live_overlaps, _replaceable_import_overlaps = await _find_existing_import_overlaps(
            session=session,
            site_id=payload.site_id,
            rows_by_key=rows_by_key,
        )
        live_overlap = {(overlap.day, overlap.metric) for overlap in live_overlaps}

        if live_overlap:
            overlap_preview = ", ".join(
                f"{day.isoformat()} {metric}" for day, metric in sorted(live_overlap)[:8]
            )
            suffix = "" if len(live_overlap) <= 8 else f", and {len(live_overlap) - 8} more"
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=(
                    "Import overlaps existing Valid-collected data. "
                    f"Remove those dates from the CSV before importing. Overlap: {overlap_preview}{suffix}"
                ),
            )

        historical_reports_to_replace = (
            await session.execute(
                select(RawReport).where(
                    RawReport.site_id == payload.site_id,
                    RawReport.day >= min(touched_days),
                    RawReport.day <= max(touched_days),
                    RawReport.kind.in_(touched_metrics),
                    RawReport.import_batch_id.is_not(None),
                )
            )
        ).scalars().all()
        for report in historical_reports_to_replace:
            if (report.day, report.kind) in rows_by_key:
                report_payload = report.payload if isinstance(report.payload, dict) else {}
                if report_payload.get("historical_import"):
                    await session.delete(report)

    actor = _normalize_username(claims.get("sub") if isinstance(claims, dict) else None)
    batch = HistoricalImportBatch(
        site_id=payload.site_id,
        source="csv",
        status="pending",
        imported_rows=len(rows_by_key),
        reduced_days=0,
        start_day=min(touched_days),
        end_day=max(touched_days),
        metrics=sorted(touched_metrics),
        created_by=actor,
    )
    session.add(batch)
    await session.flush()

    for row in rows_by_key.values():
        session.add(
            RawReport(
                site_id=payload.site_id,
                kind=row.metric,
                day=row.day,
                payload={"historical_import": True, "value": row.value, "import_batch_id": batch.id},
                import_batch_id=batch.id,
                epsilon_used=0.0,
                sampling_rate=1.0,
                server_received_at=dt.datetime.combine(row.day, dt.time(12, 0), tzinfo=dt.timezone.utc),
            )
        )
        inserted += 1
    await session.commit()

    start_day = min(touched_days)
    end_day = max(touched_days)
    try:
        await reduce_reports(session, start_day=start_day, end_day=end_day)
        await _refresh_forecasts(session, site_id=payload.site_id, plan=target_plan)
    except Exception as exc:
        batch = await session.get(HistoricalImportBatch, batch.id)
        if batch:
            batch.status = "failed"
            batch.error = str(exc)[:2000]
            await session.commit()
        raise

    batch = await session.get(HistoricalImportBatch, batch.id)
    if batch:
        batch.status = "completed"
        batch.reduced_days = len(touched_days)
        batch.completed_at = dt.datetime.now(dt.timezone.utc)
        batch.error = None
        await session.commit()

    return HistoricalImportResponse(
        site_id=payload.site_id,
        imported_rows=inserted,
        reduced_days=len(touched_days),
        batch_id=batch.id if batch else None,
    )


@router.post("/import/historical", response_model=HistoricalImportResponse)
async def import_historical(
    payload: HistoricalImportRequest,
    auth_claims: dict | None = Depends(require_dashboard_auth),
    session: AsyncSession = Depends(get_session),
):
    target_plan = await _require_standard_import_access(payload.site_id, auth_claims, session)
    return await _import_rows(payload, session, target_plan=target_plan, claims=auth_claims)


@router.post("/import/historical-csv", response_model=HistoricalImportResponse)
async def import_historical_csv(
    payload: HistoricalCsvImportRequest,
    auth_claims: dict | None = Depends(require_dashboard_auth),
    session: AsyncSession = Depends(get_session),
):
    rows, errors = _parse_historical_csv(payload.csv_text)
    if errors:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=errors[0])

    parsed_payload = HistoricalImportRequest(
        site_id=payload.site_id,
        rows=rows,
    )
    target_plan = await _require_standard_import_access(payload.site_id, auth_claims, session)
    return await _import_rows(parsed_payload, session, target_plan=target_plan, claims=auth_claims)


@router.post("/import/historical-csv/preview", response_model=HistoricalImportPreviewResponse)
async def preview_historical_csv(
    payload: HistoricalCsvImportRequest,
    auth_claims: dict | None = Depends(require_dashboard_auth),
    session: AsyncSession = Depends(get_session),
) -> HistoricalImportPreviewResponse:
    await _require_standard_import_access(payload.site_id, auth_claims, session)
    rows, errors = _parse_historical_csv(payload.csv_text)
    if not rows and not errors:
        errors = ["CSV has no import rows."]
    rows_by_key = {(row.day, row.metric): row for row in rows}
    live_overlaps, replaceable_import_overlaps = await _find_existing_import_overlaps(
        session=session,
        site_id=payload.site_id,
        rows_by_key=rows_by_key,
    )
    touched_days = {row.day for row in rows}
    metrics = sorted({row.metric for row in rows})
    warnings: list[str] = []
    if live_overlaps:
        warnings.append(
            "Some rows overlap Valid-collected data. Remove those dates before importing to avoid double-counting."
        )
    if replaceable_import_overlaps:
        warnings.append(
            "Some rows match a previous historical import. Importing will replace those imported rows."
        )

    return HistoricalImportPreviewResponse(
        site_id=payload.site_id,
        valid=not errors and not live_overlaps and bool(rows),
        row_count=len(rows),
        day_count=len(touched_days),
        start_day=min(touched_days) if touched_days else None,
        end_day=max(touched_days) if touched_days else None,
        metrics=metrics,
        errors=errors,
        warnings=warnings,
        live_overlaps=live_overlaps,
        replaceable_import_overlaps=replaceable_import_overlaps,
    )


@router.get("/import/history", response_model=HistoricalImportHistoryResponse)
async def import_history(
    site_id: str,
    auth_claims: dict | None = Depends(require_dashboard_auth),
    session: AsyncSession = Depends(get_session),
) -> HistoricalImportHistoryResponse:
    await _require_standard_import_access(site_id, auth_claims, session)
    batches = (
        await session.execute(
            select(HistoricalImportBatch)
            .where(HistoricalImportBatch.site_id == site_id)
            .order_by(desc(HistoricalImportBatch.created_at), desc(HistoricalImportBatch.id))
            .limit(50)
        )
    ).scalars().all()
    return HistoricalImportHistoryResponse(
        site_id=site_id,
        batches=[await _batch_response(session, batch) for batch in batches],
    )


@router.post("/import/batches/{batch_id}/rollback", response_model=HistoricalImportRollbackResponse)
async def rollback_import_batch(
    batch_id: int,
    site_id: str,
    auth_claims: dict | None = Depends(require_dashboard_auth),
    session: AsyncSession = Depends(get_session),
) -> HistoricalImportRollbackResponse:
    target_plan = await _require_standard_import_access(site_id, auth_claims, session)
    batch = await session.get(HistoricalImportBatch, batch_id)
    if not batch or batch.site_id != site_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Import batch not found")
    if batch.status == "rolled_back":
        return HistoricalImportRollbackResponse(
            site_id=site_id,
            batch_id=batch_id,
            status=batch.status,
            deleted_rows=0,
            reduced_days=batch.reduced_days,
        )

    rows = (
        await session.execute(
            select(RawReport)
            .where(RawReport.site_id == site_id, RawReport.import_batch_id == batch_id)
            .order_by(RawReport.day.asc(), RawReport.kind.asc(), RawReport.id.asc())
        )
    ).scalars().all()
    if not rows:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Rollback is no longer available because the batch's raw import rows are not retained.",
        )

    deleted_rows = len(rows)
    start_day = min(row.day for row in rows)
    end_day = max(row.day for row in rows)
    for row in rows:
        await session.delete(row)
    batch.status = "rolled_back"
    batch.rolled_back_at = dt.datetime.now(dt.timezone.utc)
    batch.error = None

    await reduce_reports(session, start_day=start_day, end_day=end_day)
    await _refresh_forecasts(session, site_id=site_id, plan=target_plan)

    return HistoricalImportRollbackResponse(
        site_id=site_id,
        batch_id=batch_id,
        status="rolled_back",
        deleted_rows=deleted_rows,
        reduced_days=len({row.day for row in rows}),
    )


async def _batch_response(session: AsyncSession, batch: HistoricalImportBatch) -> HistoricalImportBatchResponse:
    retained_rows = int(
        (
            await session.execute(
                select(func.count(RawReport.id)).where(
                    RawReport.site_id == batch.site_id,
                    RawReport.import_batch_id == batch.id,
                )
            )
        ).scalar_one()
        or 0
    )
    return HistoricalImportBatchResponse(
        id=batch.id,
        site_id=batch.site_id,
        source=batch.source,
        status=batch.status,
        imported_rows=batch.imported_rows,
        reduced_days=batch.reduced_days,
        start_day=batch.start_day,
        end_day=batch.end_day,
        metrics=list(batch.metrics or []),
        created_by=batch.created_by,
        created_at=batch.created_at,
        completed_at=batch.completed_at,
        rolled_back_at=batch.rolled_back_at,
        error=batch.error,
        rollback_available=batch.status in {"completed", "failed"} and retained_rows > 0,
    )


async def _refresh_forecasts(session: AsyncSession, *, site_id: str, plan: str) -> None:
    for metric in ["pageviews", "sessions", "uniques", "conversions", "revenue"]:
        await refresh_site_metric_forecast(session, site_id=site_id, metric=metric, plan=plan)
