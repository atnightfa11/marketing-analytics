from __future__ import annotations

import asyncio
import os

from fastapi import FastAPI, HTTPException
import httpx

app = FastAPI()
collect_url = os.environ.get("COLLECT_URL", "http://localhost:8000/api/collect")
collect_token = os.environ.get("COLLECT_ENDPOINT_TOKEN", "")
bypass_delay = os.environ.get("BYPASS_DELAY") == "true"


@app.post("/api/shuffle")
async def shuffle_proxy(payload: dict):
    if "batch" not in payload:
        raise HTTPException(status_code=400, detail="batch required")
    if not bypass_delay:
        await asyncio.sleep(2)
    headers = {"X-Collect-Token": collect_token} if collect_token else {}
    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.post(collect_url, json={
            "site_id": payload.get("batch", [{}])[0].get("site_id"),
            "server_received_at": payload.get("server_received_at"),
            "reports": payload["batch"],
        }, headers=headers)
        resp.raise_for_status()
    return {"status": "ok"}
