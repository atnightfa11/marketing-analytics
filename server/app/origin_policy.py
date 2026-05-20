from __future__ import annotations

import ipaddress
from dataclasses import dataclass
from fnmatch import fnmatch
from urllib.parse import urlsplit


_GLOB_CHARS = set("*?[]")


@dataclass(frozen=True)
class ParsedOrigin:
    scheme: str
    host: str
    port: int | None
    normalized: str


def _normalize_host(host: str) -> str:
    return host.strip().lower().rstrip(".")


def _scope_host(host: str) -> str:
    normalized = _normalize_host(host)
    if normalized.startswith("www."):
        return normalized[4:]
    return normalized


def _is_ip_host(host: str) -> bool:
    try:
        ipaddress.ip_address(host)
        return True
    except ValueError:
        return False


def parse_origin(value: str) -> ParsedOrigin | None:
    try:
        parsed = urlsplit(value.strip())
    except Exception:
        return None
    scheme = parsed.scheme.lower()
    if scheme not in {"http", "https"}:
        return None
    if not parsed.netloc or not parsed.hostname:
        return None
    try:
        port = parsed.port
    except ValueError:
        return None
    host = _normalize_host(parsed.hostname)
    normalized = f"{scheme}://{parsed.netloc.lower()}"
    return ParsedOrigin(scheme=scheme, host=host, port=port, normalized=normalized)


def origin_matches_allowed_pattern(origin: str, allowed_pattern: str) -> bool:
    request_origin = parse_origin(origin)
    if request_origin is None:
        return False

    pattern = allowed_pattern.strip()
    if not pattern:
        return False

    # Backward-compatible glob behavior for explicitly wildcarded patterns.
    if any(char in pattern for char in _GLOB_CHARS):
        return fnmatch(request_origin.normalized, pattern)

    allowed_origin = parse_origin(pattern)
    if allowed_origin is None:
        return False

    if request_origin.scheme != allowed_origin.scheme:
        return False

    # If a specific port is configured, require exact port match.
    if allowed_origin.port is not None and request_origin.port != allowed_origin.port:
        return False

    if request_origin.host == allowed_origin.host:
        return True

    # For domain hosts, accept apex + subdomains + www variants of the same scope.
    # Example: allowed=https://example.com matches https://www.example.com and https://app.example.com.
    if _is_ip_host(allowed_origin.host) or _is_ip_host(request_origin.host):
        return False

    request_scope = _scope_host(request_origin.host)
    allowed_scope = _scope_host(allowed_origin.host)
    if request_scope == allowed_scope:
        return True
    return request_scope.endswith(f".{allowed_scope}")
