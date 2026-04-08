#!/usr/bin/env python3
from __future__ import annotations

import argparse
import asyncio
import os
import secrets
import sys
from urllib.parse import urlsplit

from argon2 import PasswordHasher
from sqlalchemy import select

# Ensure `app` imports work regardless of current working directory.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.models import SiteApiKey, async_session_factory


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Rotate or deactivate site API keys.")
    parser.add_argument("--site-id", required=True)
    parser.add_argument("--key-id", default=None, help="Key id to deactivate (optional)")
    parser.add_argument("--deactivate-only", action="store_true", help="Only deactivate key(s)")
    parser.add_argument("--origin", default=None, help="Origin pattern for replacement key")
    parser.add_argument(
        "--allow-wildcard-origin",
        action="store_true",
        help="Allow '*' wildcard in origin pattern (disabled by default).",
    )
    parser.add_argument("--prefix", default="vsk")
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
    async with async_session_factory() as session:
        stmt = select(SiteApiKey).where(SiteApiKey.site_id == args.site_id)
        keys = (await session.execute(stmt)).scalars().all()
        for record in keys:
            if args.key_id and record.key_id != args.key_id:
                continue
            record.is_active = False

        new_key = None
        if not args.deactivate_only:
            key_id = secrets.token_hex(8)
            secret = secrets.token_urlsafe(24)
            new_key = f"{args.prefix}_{key_id}_{secret}"
            allowed_origin_input = args.origin or (keys[0].allowed_origin_pattern if keys else "*")
            allowed_origin = normalize_origin_pattern(allowed_origin_input, args.allow_wildcard_origin)
            session.add(
                SiteApiKey(
                    site_id=args.site_id,
                    key_id=key_id,
                    key_prefix=f"{args.prefix}_{key_id}",
                    key_hash=PasswordHasher().hash(new_key),
                    allowed_origin_pattern=allowed_origin,
                    is_active=True,
                )
            )
        await session.commit()

    if new_key:
        print("Replacement site key:")
        print(new_key)
    else:
        print("Key(s) deactivated.")


if __name__ == "__main__":
    asyncio.run(main())
