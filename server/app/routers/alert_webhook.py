from __future__ import annotations

import json
import logging

from fastapi import APIRouter, BackgroundTasks, Depends, status
from httpx import AsyncClient

from ..access_control import require_alert_webhook_token
from ..config import get_settings
from ..schemas import AlertWebhookPayload

logger = logging.getLogger("marketing-analytics.alerts")
router = APIRouter(tags=["alerts"])
settings = get_settings()


async def forward_to_sidecar(payload: AlertWebhookPayload):
    async with AsyncClient(timeout=10.0) as client:
        await client.post(settings.ALERT_SIDECAR_URL, json=payload.dict())


@router.post(
    "/alert/webhook",
    status_code=status.HTTP_202_ACCEPTED,
    dependencies=[Depends(require_alert_webhook_token)],
)
async def webhook(payload: AlertWebhookPayload, background: BackgroundTasks):
    logger.info("Received alert webhook %s", json.dumps(payload.dict(), sort_keys=True))
    background.add_task(forward_to_sidecar, payload)
