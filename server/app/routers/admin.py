from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import update
from datetime import datetime, timezone
from ..models import UploadToken
from ..db import get_db

router = APIRouter()

class RevokeById(BaseModel):
    token_id: int

class RevokeBySite(BaseModel):
    site_id: str

@router.post('/api/admin/revoke-token')
async def revoke_token(body: RevokeById, db: AsyncSession = Depends(get_db)):
    now = datetime.now(timezone.utc)
    await db.execute(
        update(UploadToken)
        .where(UploadToken.id == body.token_id)
        .values(revoked_at=now)
    )
    await db.commit()
    return {'ok': True}

@router.post('/api/admin/revoke-tokens')
async def revoke_tokens(body: RevokeBySite, db: AsyncSession = Depends(get_db)):
    now = datetime.now(timezone.utc)
    await db.execute(
        update(UploadToken)
        .where(UploadToken.site_id == body.site_id)
        .values(revoked_at=now)
    )
    await db.commit()
    return {'ok': True}
