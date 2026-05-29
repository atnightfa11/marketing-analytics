from __future__ import annotations

import datetime as dt

from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession

from .config import get_settings
from .models import UploadToken

settings = get_settings()
_last_upload_token_purge_at: dt.datetime | None = None


async def purge_expired_upload_tokens(
    session: AsyncSession,
    *,
    now: dt.datetime | None = None,
) -> int:
    effective_now = now or dt.datetime.now(dt.timezone.utc)
    grace_seconds = max(0, settings.UPLOAD_TOKEN_PURGE_GRACE_SECONDS)
    cutoff = effective_now - dt.timedelta(seconds=grace_seconds)
    result = await session.execute(delete(UploadToken).where(UploadToken.exp < cutoff))
    await session.commit()
    rowcount = result.rowcount
    return int(rowcount) if rowcount and rowcount > 0 else 0


async def maybe_purge_expired_upload_tokens(
    session: AsyncSession,
    *,
    now: dt.datetime | None = None,
) -> int:
    global _last_upload_token_purge_at

    effective_now = now or dt.datetime.now(dt.timezone.utc)
    interval_seconds = max(1, settings.UPLOAD_TOKEN_PURGE_INTERVAL_SECONDS)
    if (
        _last_upload_token_purge_at
        and (effective_now - _last_upload_token_purge_at).total_seconds() < interval_seconds
    ):
        return 0

    _last_upload_token_purge_at = effective_now
    return await purge_expired_upload_tokens(session, now=effective_now)
