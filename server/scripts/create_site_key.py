#!/usr/bin/env python3
from __future__ import annotations

import argparse
import asyncio
import os
import secrets
import sys
from urllib.parse import urlsplit

from argon2 import PasswordHasher

# Ensure `app` imports work regardless of current working directory.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.models import SiteApiKey, async_session_factory


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Create a site API key for SDK bootstrap.")
    parser.add_argument("--site-id", required=True, help="Site id")
    parser.add_argument("--origin", required=True, help="Allowed origin pattern (fnmatch)")
    parser.add_argument(
        "--allow-wildcard-origin",
        action="store_true",
        help="Allow '*' wildcard in origin pattern (disabled by default).",
    )
    parser.add_argument("--prefix", default="vsk", help="Site key prefix")
    return parser


def normalize_origin_pattern(value: str, allow_wildcard: bool) -> str:
    origin = value.strip()
    if "*" in origin:
        if not allow_wildcard:
            raise ValueError("Wildcard origins are disabled. Pass --allow-wildcard-origin to override.")
        return origin

    parsed = urlsplit(origin)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError("Origin must be a full origin like https://example.com")
    return f"{parsed.scheme}://{parsed.netloc}"


async def main() -> None:
    args = build_parser().parse_args()
    allowed_origin = normalize_origin_pattern(args.origin, args.allow_wildcard_origin)
    key_id = secrets.token_hex(8)
    secret = secrets.token_urlsafe(24)
    plaintext_key = f"{args.prefix}_{key_id}_{secret}"
    password_hasher = PasswordHasher()
    key_hash = password_hasher.hash(plaintext_key)

    async with async_session_factory() as session:
        session.add(
            SiteApiKey(
                site_id=args.site_id,
                key_id=key_id,
                key_prefix=f"{args.prefix}_{key_id}",
                key_hash=key_hash,
                allowed_origin_pattern=allowed_origin,
                is_active=True,
            )
        )
        await session.commit()

    print("Site key created:")
    print(plaintext_key)
    print("Store it securely; it will not be shown again.")


if __name__ == "__main__":
    asyncio.run(main())
