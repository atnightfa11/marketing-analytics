from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import insert
from datetime import datetime, timezone, timedelta
from jose import jwt
from argon2 import PasswordHasher
from ..config import settings
from ..models import UploadToken
from ..db import get_db  # project-provided

router = APIRouter()
ph = PasswordHasher()

class IssueTokenReq(BaseModel):
    site_id: str
    allowed_origin: str  # supports wildcards like *.example.com
    ttl_seconds: int | None = None

class IssueTokenRes(BaseModel):
    token: str
    token_id: int
    exp: int

@router.post('/api/upload-token', response_model=IssueTokenRes)
async def issue_token(req: IssueTokenReq, db: AsyncSession = Depends(get_db)):
    ttl = req.ttl_seconds or settings.UPLOAD_TOKEN_TTL_SECONDS
    now = datetime.now(timezone.utc)
    exp = now + timedelta(seconds=ttl)
    # Create DB record first to get id for tid
    result = await db.execute(insert(UploadToken).values(
        site_id=req.site_id,
        token_hash='placeholder',  # will update after signing
        iat=now,
        exp=exp
    ).returning(UploadToken.id))
    token_id = result.scalar_one()
    claims = {
        'tid': token_id,
        'site_id': req.site_id,
        'allowed_origin': req.allowed_origin,
        'iat': int(now.timestamp()),
        'exp': int(exp.timestamp()),
        'jti': ph.hash(f'{req.site_id}:{now.timestamp()}')[:32]  # short nonce seed
    }
    token = jwt.encode(claims, settings.UPLOAD_TOKEN_SECRET, algorithm='HS256')
    # Store hash
    await db.execute(
        UploadToken.__table__.update()
        .where(UploadToken.id == token_id)
        .values(token_hash=ph.hash(token))
    )
    await db.commit()
    return IssueTokenRes(token=token, token_id=token_id, exp=claims['exp'])
