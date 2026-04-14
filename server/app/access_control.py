from __future__ import annotations

import secrets

from fastapi import Header, HTTPException, status

from .config import get_settings

settings = get_settings()


def _require_token(expected: str | None, provided: str | None, *, token_name: str) -> None:
    if not expected:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"{token_name} is not configured",
        )
    if not provided or not secrets.compare_digest(provided, expected):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=f"Invalid {token_name}")


def require_admin_api_token(x_admin_token: str | None = Header(default=None, alias="X-Admin-Token")) -> None:
    _require_token(settings.ADMIN_API_TOKEN, x_admin_token, token_name="admin token")


def require_collect_endpoint_token(
    x_collect_token: str | None = Header(default=None, alias="X-Collect-Token")
) -> None:
    expected = settings.COLLECT_ENDPOINT_TOKEN or settings.ADMIN_API_TOKEN
    _require_token(expected, x_collect_token, token_name="collect endpoint token")

