from __future__ import annotations

import base64
import datetime as dt
import hashlib
import hmac
import json
import secrets
from functools import lru_cache
from typing import Any

from argon2 import PasswordHasher, exceptions as argon_exceptions
from fastapi import Header, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from .config import Settings, get_settings
from .models import DashboardSite, DashboardUser

settings: Settings = get_settings()
password_hasher = PasswordHasher()


def _b64url_encode(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode("utf-8").rstrip("=")


def _b64url_decode(encoded: str) -> bytes:
    return base64.urlsafe_b64decode(encoded + "=" * (-len(encoded) % 4))


def _require_auth_config() -> None:
    if not settings.DASHBOARD_AUTH_SECRET:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Dashboard auth is enabled but credentials are not configured",
        )


def create_access_token(username: str) -> tuple[str, dt.datetime]:
    _require_auth_config()
    now = dt.datetime.now(dt.timezone.utc)
    expires_at = now + dt.timedelta(seconds=max(60, settings.DASHBOARD_AUTH_TTL_SECONDS))
    header = {"alg": "HS256", "typ": "JWT"}
    payload = {
        "sub": username,
        "iat": int(now.timestamp()),
        "exp": int(expires_at.timestamp()),
    }
    header_b64 = _b64url_encode(json.dumps(header, separators=(",", ":"), sort_keys=True).encode("utf-8"))
    payload_b64 = _b64url_encode(json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8"))
    signing_input = f"{header_b64}.{payload_b64}".encode("utf-8")
    signature = hmac.new(settings.DASHBOARD_AUTH_SECRET.encode("utf-8"), signing_input, hashlib.sha256).digest()
    token = f"{header_b64}.{payload_b64}.{_b64url_encode(signature)}"
    return token, expires_at


def _decode_access_token(token: str) -> dict[str, Any]:
    _require_auth_config()
    try:
        parts = token.split(".")
        if len(parts) != 3:
            raise ValueError("Invalid token")
        header_b64, payload_b64, signature_b64 = parts
        signing_input = f"{header_b64}.{payload_b64}".encode("utf-8")
        expected_sig = hmac.new(settings.DASHBOARD_AUTH_SECRET.encode("utf-8"), signing_input, hashlib.sha256).digest()
        provided_sig = _b64url_decode(signature_b64)
        if not hmac.compare_digest(provided_sig, expected_sig):
            raise ValueError("Invalid signature")
        payload = json.loads(_b64url_decode(payload_b64))
        exp = int(payload.get("exp", 0))
        if dt.datetime.now(dt.timezone.utc).timestamp() > exp:
            raise ValueError("Token expired")
        return payload
    except Exception as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid auth token") from exc


def validate_credentials(username: str, password: str) -> bool:
    _require_auth_config()
    users = _parsed_auth_users()
    if users:
        expected_password = users.get(username)
        return isinstance(expected_password, str) and secrets.compare_digest(password, expected_password)
    configured_username = settings.DASHBOARD_AUTH_USERNAME
    configured_password = settings.DASHBOARD_AUTH_PASSWORD
    if not configured_username or not configured_password:
        return False
    return secrets.compare_digest(username, configured_username) and secrets.compare_digest(password, configured_password)


async def validate_credentials_async(username: str, password: str, session: AsyncSession) -> bool:
    if validate_credentials(username, password):
        return True
    user = await session.get(DashboardUser, username)
    if not user:
        return False
    try:
        password_hasher.verify(user.password_hash, password)
    except argon_exceptions.VerifyMismatchError:
        return False
    return True


def require_dashboard_auth(authorization: str | None = Header(default=None)) -> dict[str, Any] | None:
    if not settings.DASHBOARD_AUTH_ENABLED:
        return None
    if not authorization:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Authorization header required")
    parts = authorization.split(" ", 1)
    if len(parts) != 2 or parts[0].lower() != "bearer":
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid authorization scheme")
    return _decode_access_token(parts[1])


@lru_cache(maxsize=8)
def _parse_auth_users(raw: str) -> dict[str, str]:
    if not raw:
        return {}
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise RuntimeError("Invalid DASHBOARD_AUTH_USERS_JSON") from exc
    if not isinstance(parsed, dict):
        raise RuntimeError("DASHBOARD_AUTH_USERS_JSON must be a JSON object")

    users: dict[str, str] = {}
    for username, value in parsed.items():
        if not isinstance(username, str):
            continue
        normalized_username = username.strip()
        if not normalized_username:
            continue
        if isinstance(value, str):
            normalized_password = value.strip()
            if normalized_password:
                users[normalized_username] = normalized_password
            continue
        if isinstance(value, dict):
            maybe_password = value.get("password")
            if isinstance(maybe_password, str) and maybe_password.strip():
                users[normalized_username] = maybe_password.strip()
    return users


def _parsed_auth_users() -> dict[str, str]:
    return _parse_auth_users(settings.DASHBOARD_AUTH_USERS_JSON or "")


@lru_cache(maxsize=8)
def _parse_site_access_map(raw: str) -> dict[str, set[str]]:
    if not raw:
        return {}
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise RuntimeError("Invalid DASHBOARD_SITE_ACCESS_JSON") from exc
    if not isinstance(parsed, dict):
        raise RuntimeError("DASHBOARD_SITE_ACCESS_JSON must be a JSON object")
    access_map: dict[str, set[str]] = {}
    for username, site_ids in parsed.items():
        if not isinstance(username, str):
            continue
        if isinstance(site_ids, str):
            ids = {site_ids.strip()} if site_ids.strip() else set()
        elif isinstance(site_ids, list):
            ids = {str(site_id).strip() for site_id in site_ids if str(site_id).strip()}
        else:
            ids = set()
        access_map[username] = ids
    return access_map


def _parsed_site_access_map() -> dict[str, set[str]]:
    return _parse_site_access_map(settings.DASHBOARD_SITE_ACCESS_JSON or "")


def get_allowed_site_ids(claims: dict[str, Any] | None) -> set[str] | None:
    if not settings.DASHBOARD_AUTH_ENABLED:
        return None

    if settings.DASHBOARD_ALLOWED_SITE_IDS:
        allowed = {item.strip() for item in settings.DASHBOARD_ALLOWED_SITE_IDS.split(",") if item.strip()}
        if "*" in allowed:
            return None
        return allowed

    user_map = _parsed_site_access_map()
    if not user_map:
        return None

    username = claims.get("sub") if isinstance(claims, dict) else None
    if not isinstance(username, str) or not username:
        return set()

    allowed = user_map.get(username)
    if allowed is None:
        return set()
    if "*" in allowed:
        return None
    return allowed


def enforce_site_access(site_id: str, claims: dict[str, Any] | None) -> None:
    allowed = get_allowed_site_ids(claims)
    if allowed is None:
        return
    if site_id not in allowed:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="You do not have access to this site")


async def enforce_site_access_with_db(
    *,
    site_id: str,
    claims: dict[str, Any] | None,
    session: AsyncSession,
) -> None:
    if not settings.DASHBOARD_AUTH_ENABLED:
        return

    allowed = get_allowed_site_ids(claims)
    if allowed is not None:
        if site_id not in allowed:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="You do not have access to this site")
        return

    username = claims.get("sub") if isinstance(claims, dict) else None
    if not isinstance(username, str) or not username:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="You do not have access to this site")

    site = await session.get(DashboardSite, site_id)
    if not site:
        if settings.DASHBOARD_ALLOW_UNCLAIMED_SITES:
            # Temporary compatibility path for legacy sites not yet claimed in dashboard_sites.
            return
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="You do not have access to this site")
    if site.owner_username != username:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="You do not have access to this site")
