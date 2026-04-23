from __future__ import annotations

import re
import secrets
from urllib.parse import urlsplit

from argon2 import PasswordHasher
from fastapi import HTTPException, status

from .config import get_settings

settings = get_settings()
password_hasher = PasswordHasher()
_slug_re = re.compile(r"[^a-z0-9]+")


def normalize_origin_pattern(value: str, allow_wildcard: bool = False) -> str:
    origin = value.strip()
    if "*" in origin:
        if not allow_wildcard:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Wildcard origins are disabled",
            )
        return origin
    parsed = urlsplit(origin)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Origin must be a full origin like https://example.com",
        )
    return f"{parsed.scheme}://{parsed.netloc}"


def canonical_origin_for_domain(domain_or_url: str) -> str:
    raw = domain_or_url.strip()
    if not raw:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="site_domain is required")
    if "://" not in raw:
        raw = f"https://{raw}"
    return normalize_origin_pattern(raw, allow_wildcard=False)


def site_id_from_domain(domain_or_origin: str) -> str:
    parsed = urlsplit(domain_or_origin if "://" in domain_or_origin else f"https://{domain_or_origin}")
    host = parsed.netloc.lower().strip()
    if not host:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid site domain")
    host_slug = _slug_re.sub("-", host).strip("-")
    if not host_slug:
        host_slug = "site"
    return f"live-{host_slug}"


def build_site_key() -> tuple[str, str, str]:
    prefix = settings.SDK_SITE_KEY_PREFIX
    key_id = secrets.token_hex(8)
    secret = secrets.token_urlsafe(24)
    plaintext_key = f"{prefix}_{key_id}_{secret}"
    return key_id, f"{prefix}_{key_id}", plaintext_key


def hash_site_key(site_key: str) -> str:
    return password_hasher.hash(site_key)

