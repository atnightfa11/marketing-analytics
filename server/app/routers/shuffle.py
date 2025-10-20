from fastapi import APIRouter, HTTPException, Request, Depends
from starlette.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession
from datetime import datetime, timezone, timedelta
from jose import jwt, JWTError
from argon2 import PasswordHasher
from fnmatch import fnmatch
import os
import asyncio
from ..config import settings
from ..models import UploadToken, TokenNonce
from ..db import get_db  # project-provided
from sqlalchemy import select, update, insert

router = APIRouter()
ph = PasswordHasher()

# in-memory token bucket: {key: (tokens, refreshed_at)}
_buckets = {}

def _bucket_ok(key: str, capacity: int, per_min: int) -> bool:
    now = datetime.now(timezone.utc)
    tokens, ts = _buckets.get(key, (capacity, now))
    # refill
    elapsed = (now - ts).total_seconds()
    refill = per_min * (elapsed / 60.0)
    tokens = min(capacity, tokens + refill)
    if tokens >= 1.0:
        tokens -= 1.0
        _buckets[key] = (tokens, now)
        return True
    _buckets[key] = (tokens, now)
    return False

async def _forward(body: bytes, content_type: str):
    import httpx
    async with httpx.AsyncClient(timeout=5.0) as client:
        r = await client.post(
            os.environ.get('INTERNAL_COLLECT_URL', 'http://localhost:8000/api/collect'),
            content=body,
            headers={'Content-Type': content_type}
        )
        r.raise_for_status()

@router.post('/api/shuffle')
async def shuffle(request: Request, db: AsyncSession = Depends(get_db)):
    auth = request.headers.get('authorization', '')
    if not auth.startswith('Bearer '):
        raise HTTPException(status_code=401, detail='missing bearer token')
    token = auth.replace('Bearer ', '').strip()
    origin = request.headers.get('origin', '') or request.headers.get('x-origin', '')
    site_id = request.headers.get('x-site-id', '')

    # Rate limit combined on site and ip
    ip = request.client.host if request.client else 'unknown'
    key = f'{site_id}:{ip}'
    if not _bucket_ok(key, settings.RATE_LIMIT_BUCKET_PER_MIN, settings.RATE_LIMIT_BUCKET_PER_MIN):
        raise HTTPException(status_code=429, detail='rate limited')

    # Validate JWT
    try:
        claims = jwt.decode(token, settings.UPLOAD_TOKEN_SECRET, algorithms=['HS256'])
    except JWTError:
        raise HTTPException(status_code=401, detail='invalid token')

    if claims.get('site_id') != site_id:
        raise HTTPException(status_code=401, detail='site mismatch')

    allowed = claims.get('allowed_origin') or ''
    if not allowed or not fnmatch(origin, allowed):
        raise HTTPException(status_code=401, detail='origin not allowed')

    exp = datetime.fromtimestamp(claims['exp'], tz=timezone.utc)
    if datetime.now(timezone.utc) >= exp:
        raise HTTPException(status_code=401, detail='token expired')

    # Revocation check
    token_id = claims.get('tid')
    if not token_id:
        raise HTTPException(status_code=401, detail='missing token id')

    result = await db.execute(select(UploadToken).where(UploadToken.id == int(token_id)))
    rec = result.scalar_one_or_none()
    if not rec or rec.revoked_at is not None:
        raise HTTPException(status_code=401, detail='token revoked')

    # Replay protection via nonce
    jti = claims.get('jti')
    if not jti:
        raise HTTPException(status_code=401, detail='missing nonce')
    exists = await db.execute(select(TokenNonce).where(TokenNonce.site_id == site_id, TokenNonce.jti == jti))
    if exists.scalar_one_or_none() is not None:
        raise HTTPException(status_code=401, detail='replay detected')
    await db.execute(insert(TokenNonce).values(site_id=site_id, jti=jti))
    await db.commit()

    # Random hold 0..120 s
    delay_ms = int.from_bytes(os.urandom(2), 'big') % 120_001
    await asyncio.sleep(delay_ms / 1000.0)

    body = await request.body()
    ct = request.headers.get('content-type', 'application/json')
    await _forward(body, ct)

    return JSONResponse({'status': 'accepted', 'delay_ms': delay_ms, 'site_id': site_id})
