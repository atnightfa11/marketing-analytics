from fastapi import APIRouter, HTTPException, Request, Depends
from pydantic import BaseModel, Field, conlist
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import insert
from datetime import datetime, timezone
from ..models import LdpReport
from ..config import settings
from ..db import get_db  # you will provide this in your project

router = APIRouter()

class PresenceReport(BaseModel):
    kind: str = Field('presence_day', const=True)
    site_id: str
    day: str                     # YYYY-MM-DD
    bit: int                     # 0 or 1
    epsilon_used: float
    sampling_rate: float = 1.0
    ts_client: float

Batch = conlist(PresenceReport, min_items=1)

@router.post('/api/collect')
async def collect(reports: Batch, request: Request, db: AsyncSession = Depends(get_db)):
    now = datetime.now(timezone.utc)
    for r in reports:
        # basic freshness using server watermark
        if abs(now.timestamp() - r.ts_client / 1000.0) > settings.MAX_OUT_OF_ORDER_SECONDS:
            # late beyond hard bound gets dropped
            continue
        stmt = insert(LdpReport).values(
            site_id=r.site_id,
            kind=r.kind,
            day=r.day,
            payload={'bit': int(r.bit)},
            epsilon_used=float(r.epsilon_used),
            sampling_rate=float(r.sampling_rate),
            server_received_at=now
        )
        await db.execute(stmt)
    await db.commit()
    return {'ok': True, 'accepted': len(reports)}
