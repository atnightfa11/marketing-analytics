#!/usr/bin/env python3
import asyncio
import datetime as dt
import json
import os
from typing import Any, Dict

import httpx

SHUFFLE_URL = os.environ.get("SHUFFLE_URL", "http://localhost:8000/api/shuffle")
UPLOAD_TOKEN = os.environ.get("UPLOAD_TOKEN")
SITE_ID = os.environ.get("SITE_ID", "demo")


def rr_bit(epsilon: float) -> Dict[str, Any]:
    import secrets
    import math

    exp = math.exp(epsilon)
    p = exp / (1 + exp)
    bit = 1 if secrets.randbelow(10_000) / 10_000 < p else 0
    return {
        "randomized_bit": bit,
        "probability_true": p,
        "probability_false": 1 - p,
        "variance": p * (1 - p),
    }


async def send_batch():
    if not UPLOAD_TOKEN:
        raise RuntimeError("UPLOAD_TOKEN is required")
    batch = []
    now = dt.datetime.now(dt.timezone.utc).isoformat()
    for _ in range(20):
        payload = rr_bit(0.5)
        batch.append(
            {
                "site_id": SITE_ID,
                "kind": "pageviews",
                "payload": payload,
                "epsilon_used": 0.5,
                "sampling_rate": 1.0,
                "client_timestamp": now,
            }
        )
    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.post(
            SHUFFLE_URL,
            headers={"Origin": "https://example.com"},
            json={"token": UPLOAD_TOKEN, "nonce": dt.datetime.now().isoformat(), "batch": batch},
        )
        resp.raise_for_status()
        print("Seed batch sent")


if __name__ == "__main__":
    asyncio.run(send_batch())
