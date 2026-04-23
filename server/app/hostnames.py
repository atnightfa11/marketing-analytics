from __future__ import annotations

from urllib.parse import urlsplit


def normalize_hostname(raw_value: str | None) -> str | None:
    if raw_value is None:
        return None
    value = raw_value.strip().lower()
    if not value:
        return None
    if "://" in value:
        parsed = urlsplit(value)
        value = parsed.netloc or parsed.path or ""
    value = value.split("/", 1)[0].split("?", 1)[0].split("#", 1)[0]
    if ":" in value:
        value = value.split(":", 1)[0]
    if value.startswith("www."):
        value = value[4:]
    return value or None


def hostname_from_request_headers(origin: str | None, referer: str | None) -> str | None:
    if origin:
        host = normalize_hostname(origin)
        if host:
            return host
    if referer:
        host = normalize_hostname(referer)
        if host:
            return host
    return None


def hostname_from_payload(payload: dict) -> str | None:
    for key in ("_hostname", "hostname", "host"):
        raw_value = payload.get(key)
        if isinstance(raw_value, str):
            host = normalize_hostname(raw_value)
            if host:
                return host
    raw_url = payload.get("url")
    if isinstance(raw_url, str) and "://" in raw_url:
        return normalize_hostname(raw_url)
    return None
