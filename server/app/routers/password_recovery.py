import datetime as dt
import hashlib
import logging
import secrets
import time
from collections import defaultdict

from fastapi import (
    APIRouter,
    BackgroundTasks,
    Depends,
    HTTPException,
    Request,
    Response,
)
from pydantic import BaseModel, Field
from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import get_settings
from ..dashboard_auth import clear_dashboard_auth_cookie, password_hasher
from ..email_delivery import send_email
from ..models import DashboardUser, PasswordReset, async_session_factory, get_session

router = APIRouter(tags=["auth"])
settings = get_settings()
attempts = defaultdict(list)
logger = logging.getLogger("marketing-analytics.password-recovery")


class ResetRequest(BaseModel):
    email: str = Field(min_length=3, max_length=255)


class ResetConfirm(BaseModel):
    token: str = Field(min_length=32, max_length=128)
    password: str = Field(min_length=8, max_length=128)


def throttle(key: str, limit: int, window: int):
    now = time.monotonic()
    recent = [at for at in attempts[key] if at > now - window]
    attempts[key] = recent
    if len(recent) >= limit:
        raise HTTPException(429, "Too many requests. Please try again later.")
    recent.append(now)
    if len(attempts) > 10000:
        for stale in list(attempts):
            if not attempts[stale] or attempts[stale][-1] < now - 3600:
                del attempts[stale]


async def deliver_reset(email: str):
    async with async_session_factory() as session:
        user = await session.scalar(
            select(DashboardUser).where(DashboardUser.email == email)
        )
        if not user:
            return
        now = dt.datetime.now(dt.timezone.utc)
        await session.execute(
            delete(PasswordReset).where(PasswordReset.expires_at < now)
        )
        token = secrets.token_urlsafe(32)
        digest = hashlib.sha256(token.encode()).hexdigest()
        session.add(
            PasswordReset(
                token_hash=digest,
                username=user.username,
                expires_at=now + dt.timedelta(minutes=30),
            )
        )
        await session.commit()
        # A fragment keeps the secret out of HTTP access logs and referrer URLs.
        link = f"{settings.PASSWORD_RESET_URL}#token={token}"
        try:
            await send_email(
                [email],
                "Reset your Valid password",
                f"Open this link to reset your Valid password:\n\n{link}\n\n"
                "This link expires in 30 minutes and can be used once. "
                "If you did not request this, you can ignore this email.",
            )
        except Exception:
            await session.execute(
                delete(PasswordReset).where(PasswordReset.token_hash == digest)
            )
            await session.commit()
            logger.error("Password reset delivery failed")


@router.post("/auth/password-reset/request")
async def request_reset(
    payload: ResetRequest, request: Request, tasks: BackgroundTasks
):
    if not settings.alert_email_configured():
        raise HTTPException(
            503, "Password reset is temporarily unavailable. Contact support."
        )
    throttle(f"ip:{request.client.host if request.client else 'unknown'}", 5, 60)
    email = payload.email.strip().lower()
    throttle(f"email:{hashlib.sha256(email.encode()).hexdigest()}", 3, 3600)
    tasks.add_task(deliver_reset, email)
    return {
        "message": "If that email belongs to an account, a reset link will arrive shortly."
    }


@router.post("/auth/password-reset/confirm")
async def confirm_reset(
    payload: ResetConfirm,
    request: Request,
    response: Response,
    session: AsyncSession = Depends(get_session),
):
    throttle(f"confirm:{request.client.host if request.client else 'unknown'}", 10, 60)
    now = dt.datetime.now(dt.timezone.utc)
    digest = hashlib.sha256(payload.token.encode()).hexdigest()
    # Claim atomically so two requests cannot both consume the same token.
    username = await session.scalar(
        update(PasswordReset)
        .where(
            PasswordReset.token_hash == digest,
            PasswordReset.used_at.is_(None),
            PasswordReset.expires_at > now,
        )
        .values(used_at=now)
        .returning(PasswordReset.username)
    )
    if not username:
        raise HTTPException(
            400, "This reset link is invalid or expired. Request a new one."
        )
    await session.execute(
        update(DashboardUser)
        .where(DashboardUser.username == username)
        .values(
            password_hash=password_hasher.hash(payload.password),
            auth_version=DashboardUser.auth_version + 1,
            updated_at=now,
        )
    )
    await session.execute(
        update(PasswordReset)
        .where(PasswordReset.username == username)
        .values(used_at=now)
    )
    await session.commit()
    clear_dashboard_auth_cookie(response)
    return {"message": "Password updated. Sign in with your new password."}
