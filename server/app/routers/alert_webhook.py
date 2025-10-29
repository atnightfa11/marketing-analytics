from __future__ import annotations

import json
import logging

from fastapi import APIRouter, BackgroundTasks, Depends, status
from httpx import AsyncClient

from ..schemas import AlertWebhookPayload

logger = logging.getLogger("marketing-analytics.alerts")
router = APIRouter(tags=["alerts"])

SLACK_SIDE_CAR_URL = "http://alerts:8080/notify"


async def forward_to_sidecar(payload: AlertWebhookPayload):
    async with AsyncClient(timeout=10.0) as client:
        await client.post(SLACK_SIDE_CAR_URL, json=payload.dict())


@router.post("/alert/webhook", status_code=status.HTTP_202_ACCEPTED)
async def webhook(payload: AlertWebhookPayload, background: BackgroundTasks):
    logger.info("Received alert webhook %s", json.dumps(payload.dict(), sort_keys=True))
    background.add_task(forward_to_sidecar, payload)
