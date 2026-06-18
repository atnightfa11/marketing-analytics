from __future__ import annotations

import re
from collections.abc import Iterable

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import PlainTextResponse, Response

from .config import Settings
from .origin_policy import parse_origin

PUBLIC_INGEST_CORS_PATHS = (
    "/api/sdk/bootstrap",
    "/api/shuffle",
    "/api/collect",
)
MUTATING_METHODS = {"POST", "PUT", "PATCH", "DELETE"}
DEFAULT_ALLOW_METHODS = "GET, POST, PUT, PATCH, DELETE, OPTIONS"
DEFAULT_ALLOW_HEADERS = "Authorization, Content-Type, X-Admin-Token, X-Collect-Token, X-Requested-With"


def _normalized_origins(values: Iterable[str]) -> set[str]:
    origins: set[str] = set()
    for value in values:
        parsed = parse_origin(value)
        if parsed:
            origins.add(parsed.normalized)
    return origins


def _normalized_origin(value: str | None) -> str | None:
    if not value:
        return None
    parsed = parse_origin(value)
    return parsed.normalized if parsed else None


class PathAwareCORSMiddleware(BaseHTTPMiddleware):
    """Apply credentialed CORS only to trusted dashboard origins.

    Browser SDK ingest is intentionally callable from customer sites, but those
    endpoints do not need cookies. Dashboard endpoints do need cookies, so their
    CORS policy must be narrow.
    """

    def __init__(self, app, settings: Settings):
        super().__init__(app)
        self.settings = settings
        self.dashboard_origins = _normalized_origins(settings.DASHBOARD_CORS_ORIGINS)
        self.public_origin_regex = re.compile(settings.cors_origin_regex) if settings.cors_origin_regex else None
        self.public_origins = _normalized_origins(settings.cors_origins)

    async def dispatch(self, request: Request, call_next):
        origin = request.headers.get("Origin")
        profile = self._profile_for_path(request.url.path)

        if request.method == "OPTIONS" and request.headers.get("Access-Control-Request-Method"):
            return self._preflight_response(request, origin, profile)

        if self._requires_dashboard_origin_check(request) and origin and not self._dashboard_origin_allowed(origin):
            return PlainTextResponse("Origin not allowed", status_code=403)

        response = await call_next(request)
        if origin:
            self._apply_actual_cors(response, origin, profile)
        return response

    def _profile_for_path(self, path: str) -> str:
        if path in PUBLIC_INGEST_CORS_PATHS:
            return "public"
        return "dashboard"

    def _requires_dashboard_origin_check(self, request: Request) -> bool:
        if request.method not in MUTATING_METHODS:
            return False
        return self._profile_for_path(request.url.path) == "dashboard"

    def _dashboard_origin_allowed(self, origin: str | None) -> bool:
        normalized = _normalized_origin(origin)
        return bool(normalized and normalized in self.dashboard_origins)

    def _public_origin_allowed(self, origin: str | None) -> bool:
        normalized = _normalized_origin(origin)
        if not normalized:
            return False
        if self.settings.cors_allow_all:
            return True
        if normalized in self.public_origins:
            return True
        return bool(self.public_origin_regex and self.public_origin_regex.fullmatch(normalized))

    def _preflight_response(self, request: Request, origin: str | None, profile: str) -> Response:
        if profile == "public":
            if not self._public_origin_allowed(origin):
                return PlainTextResponse("CORS origin not allowed", status_code=400)
            headers = self._cors_preflight_headers(request, allow_origin="*", allow_credentials=False)
            return Response(status_code=204, headers=headers)

        if not self._dashboard_origin_allowed(origin):
            return PlainTextResponse("CORS origin not allowed", status_code=400)
        headers = self._cors_preflight_headers(request, allow_origin=origin or "", allow_credentials=True)
        return Response(status_code=204, headers=headers)

    def _cors_preflight_headers(self, request: Request, *, allow_origin: str, allow_credentials: bool) -> dict[str, str]:
        requested_headers = request.headers.get("Access-Control-Request-Headers")
        headers = {
            "Access-Control-Allow-Origin": allow_origin,
            "Access-Control-Allow-Methods": DEFAULT_ALLOW_METHODS,
            "Access-Control-Allow-Headers": requested_headers or DEFAULT_ALLOW_HEADERS,
            "Access-Control-Max-Age": "600",
        }
        if allow_origin != "*":
            headers["Vary"] = "Origin"
        if allow_credentials:
            headers["Access-Control-Allow-Credentials"] = "true"
        return headers

    def _apply_actual_cors(self, response: Response, origin: str, profile: str) -> None:
        if profile == "public":
            if self._public_origin_allowed(origin):
                response.headers["Access-Control-Allow-Origin"] = "*"
                response.headers.setdefault("Access-Control-Expose-Headers", "Retry-After")
            return

        if self._dashboard_origin_allowed(origin):
            response.headers["Access-Control-Allow-Origin"] = origin
            response.headers["Access-Control-Allow-Credentials"] = "true"
            response.headers.setdefault("Access-Control-Expose-Headers", "Retry-After")
            response.headers.add_vary_header("Origin")
