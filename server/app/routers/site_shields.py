from __future__ import annotations

import datetime as dt
import ipaddress

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..dashboard_auth import enforce_site_access_with_db, require_dashboard_auth
from ..dependencies import require_site_access
from ..models import SiteIpBlock, get_session
from ..schemas import SiteIpBlockCreateRequest, SiteIpBlockListResponse, SiteIpBlockResponse

router = APIRouter(prefix="/site-shields", tags=["settings"])


def normalize_ip_block(value: str) -> str:
    cleaned = value.strip()
    if not cleaned:
        raise ValueError("IP address or CIDR range is required")
    try:
        if "/" in cleaned:
            return str(ipaddress.ip_network(cleaned, strict=False))
        return str(ipaddress.ip_network(ipaddress.ip_address(cleaned)))
    except ValueError as exc:
        raise ValueError("Enter a valid IP address or CIDR range") from exc


def _serialize(block: SiteIpBlock) -> SiteIpBlockResponse:
    return SiteIpBlockResponse(
        id=block.id,
        site_id=block.site_id,
        cidr=block.cidr,
        label=block.label,
        created_by=block.created_by,
        created_at=block.created_at,
    )


@router.get("/ip-blocks", response_model=SiteIpBlockListResponse, dependencies=[Depends(require_dashboard_auth)])
async def list_ip_blocks(
    site_id: str,
    _: None = Depends(require_site_access),
    session: AsyncSession = Depends(get_session),
) -> SiteIpBlockListResponse:
    rows = (
        await session.execute(
            select(SiteIpBlock)
            .where(SiteIpBlock.site_id == site_id)
            .order_by(SiteIpBlock.created_at.desc(), SiteIpBlock.id.desc())
        )
    ).scalars().all()
    return SiteIpBlockListResponse(site_id=site_id, blocks=[_serialize(row) for row in rows])


@router.post("/ip-blocks", response_model=SiteIpBlockListResponse, dependencies=[Depends(require_dashboard_auth)])
async def create_ip_block(
    payload: SiteIpBlockCreateRequest,
    claims: dict | None = Depends(require_dashboard_auth),
    session: AsyncSession = Depends(get_session),
) -> SiteIpBlockListResponse:
    await enforce_site_access_with_db(site_id=payload.site_id, claims=claims, session=session)
    try:
        cidr = normalize_ip_block(payload.cidr)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    existing = (
        await session.execute(
            select(SiteIpBlock).where(SiteIpBlock.site_id == payload.site_id, SiteIpBlock.cidr == cidr)
        )
    ).scalar_one_or_none()
    if existing is not None:
        raise HTTPException(status_code=409, detail="That IP block is already configured")

    username = claims.get("sub") if isinstance(claims, dict) else None
    label = " ".join(payload.label.strip().split()) if isinstance(payload.label, str) and payload.label.strip() else None
    session.add(
        SiteIpBlock(
            site_id=payload.site_id,
            cidr=cidr,
            label=label,
            created_by=username.strip().lower() if isinstance(username, str) and username.strip() else None,
            created_at=dt.datetime.now(dt.timezone.utc),
        )
    )
    await session.commit()
    return await list_ip_blocks(site_id=payload.site_id, session=session)


@router.delete("/ip-blocks/{block_id}", response_model=SiteIpBlockListResponse, dependencies=[Depends(require_dashboard_auth)])
async def delete_ip_block(
    block_id: int,
    site_id: str,
    _: None = Depends(require_site_access),
    session: AsyncSession = Depends(get_session),
) -> SiteIpBlockListResponse:
    block = await session.get(SiteIpBlock, block_id)
    if block is None or block.site_id != site_id:
        raise HTTPException(status_code=404, detail="IP block not found")
    await session.delete(block)
    await session.commit()
    return await list_ip_blocks(site_id=site_id, session=session)
