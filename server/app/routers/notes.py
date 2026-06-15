from __future__ import annotations

import datetime as dt

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..dashboard_auth import enforce_site_access_with_db, require_dashboard_auth
from ..models import DashboardNote, get_session
from ..schemas import (
    DashboardNoteCreateRequest,
    DashboardNoteResponse,
    DashboardNotesResponse,
    DashboardNoteUpdateRequest,
)

router = APIRouter(prefix="/notes", tags=["notes"])

NOTE_METRICS = {"pageviews", "uniques", "sessions", "conversions", "revenue"}


def _clean_body(value: str) -> str:
    cleaned = " ".join(value.strip().split())
    if not cleaned:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Note body is required")
    if len(cleaned) > 1200:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Note body is too long")
    return cleaned


def _clean_metric(value: str | None) -> str | None:
    if value is None:
        return None
    cleaned = value.strip().lower()
    if not cleaned:
        return None
    if cleaned not in NOTE_METRICS:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid note metric")
    return cleaned


def _note_response(note: DashboardNote) -> DashboardNoteResponse:
    return DashboardNoteResponse(
        id=note.id,
        site_id=note.site_id,
        day=note.day,
        body=note.body,
        metric=note.metric,
        created_by=note.created_by,
        created_at=note.created_at,
        updated_at=note.updated_at,
    )


@router.get("", response_model=DashboardNotesResponse)
async def list_notes(
    site_id: str,
    start: dt.date | None = None,
    end: dt.date | None = None,
    claims: dict | None = Depends(require_dashboard_auth),
    session: AsyncSession = Depends(get_session),
) -> DashboardNotesResponse:
    await enforce_site_access_with_db(site_id=site_id, claims=claims, session=session)
    stmt = select(DashboardNote).where(DashboardNote.site_id == site_id)
    if start is not None:
        stmt = stmt.where(DashboardNote.day >= start)
    if end is not None:
        stmt = stmt.where(DashboardNote.day <= end)
    rows = (
        await session.execute(
            stmt.order_by(DashboardNote.day.desc(), DashboardNote.created_at.desc()).limit(200)
        )
    ).scalars().all()
    return DashboardNotesResponse(site_id=site_id, notes=[_note_response(note) for note in rows])


@router.post("", response_model=DashboardNoteResponse, status_code=status.HTTP_201_CREATED)
async def create_note(
    payload: DashboardNoteCreateRequest,
    claims: dict | None = Depends(require_dashboard_auth),
    session: AsyncSession = Depends(get_session),
) -> DashboardNoteResponse:
    await enforce_site_access_with_db(site_id=payload.site_id, claims=claims, session=session)
    username = claims.get("sub") if isinstance(claims, dict) else None
    note = DashboardNote(
        site_id=payload.site_id,
        day=payload.day,
        body=_clean_body(payload.body),
        metric=_clean_metric(payload.metric),
        created_by=username.strip().lower() if isinstance(username, str) and username.strip() else None,
        updated_at=dt.datetime.now(dt.timezone.utc),
    )
    session.add(note)
    await session.commit()
    await session.refresh(note)
    return _note_response(note)


@router.put("/{note_id}", response_model=DashboardNoteResponse)
async def update_note(
    note_id: int,
    payload: DashboardNoteUpdateRequest,
    claims: dict | None = Depends(require_dashboard_auth),
    session: AsyncSession = Depends(get_session),
) -> DashboardNoteResponse:
    await enforce_site_access_with_db(site_id=payload.site_id, claims=claims, session=session)
    note = await session.get(DashboardNote, note_id)
    if note is None or note.site_id != payload.site_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Note not found")
    if payload.day is not None:
        note.day = payload.day
    if payload.body is not None:
        note.body = _clean_body(payload.body)
    fields_set = getattr(payload, "model_fields_set", getattr(payload, "__fields_set__", set()))
    if "metric" in fields_set:
        note.metric = _clean_metric(payload.metric)
    note.updated_at = dt.datetime.now(dt.timezone.utc)
    await session.commit()
    await session.refresh(note)
    return _note_response(note)


@router.delete("/{note_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_note(
    note_id: int,
    site_id: str,
    claims: dict | None = Depends(require_dashboard_auth),
    session: AsyncSession = Depends(get_session),
) -> Response:
    await enforce_site_access_with_db(site_id=site_id, claims=claims, session=session)
    note = await session.get(DashboardNote, note_id)
    if note is None or note.site_id != site_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Note not found")
    await session.delete(note)
    await session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
