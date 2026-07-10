from __future__ import annotations

import hmac

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import PlainTextResponse

from .config import Settings


class MetricsAuthMiddleware(BaseHTTPMiddleware):
    def __init__(self, app, settings: Settings):
        super().__init__(app)
        self.settings = settings

    async def dispatch(self, request: Request, call_next):
        if request.url.path != "/metrics":
            return await call_next(request)

        if self.settings.METRICS_PUBLIC:
            return await call_next(request)

        expected = self.settings.METRICS_AUTH_TOKEN
        if not expected:
            return PlainTextResponse("Not found", status_code=404)

        provided = _metrics_token_from_request(request)
        if provided and hmac.compare_digest(provided, expected):
            return await call_next(request)

        return PlainTextResponse("Metrics token required", status_code=401)


def _metrics_token_from_request(request: Request) -> str | None:
    header_token = request.headers.get("X-Metrics-Token")
    if header_token:
        return header_token.strip()

    authorization = request.headers.get("Authorization", "")
    scheme, _, token = authorization.partition(" ")
    if scheme.lower() == "bearer" and token.strip():
        return token.strip()
    return None
