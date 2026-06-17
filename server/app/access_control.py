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
    # The collect endpoint is a cross-tenant write surface, so it must carry its own
    # dedicated token. Do not fall back to ADMIN_API_TOKEN: that would let a single
    # leaked admin credential write events for any site.
    _require_token(settings.COLLECT_ENDPOINT_TOKEN, x_collect_token, token_name="collect endpoint token")


def require_alert_webhook_token(
    x_alert_token: str | None = Header(default=None, alias="X-Alert-Token")
) -> None:
    _require_token(settings.ALERT_WEBHOOK_TOKEN, x_alert_token, token_name="alert webhook token")

