from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import Response
from typing import Callable
from .config import settings

class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next: Callable):
        resp: Response = await call_next(request)
        # HSTS
        resp.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
        # Basic CSP for API
        resp.headers["Content-Security-Policy"] = "default-src 'none'"
        # Other sane defaults
        resp.headers["X-Content-Type-Options"] = "nosniff"
        resp.headers["X-Frame-Options"] = "DENY"
        resp.headers["Referrer-Policy"] = "no-referrer"
        return resp
