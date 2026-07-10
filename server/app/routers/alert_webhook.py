from __future__ import annotations

import json
import logging

from fastapi import APIRouter, BackgroundTasks, Depends, status

from ..access_control import require_alert_webhook_token
from ..ops_alerts import deliver_ops_alert_payload
from ..schemas import AlertWebhookPayload

logger = logging.getLogger("marketing-analytics.alerts")
router = APIRouter(tags=["alerts"])


@router.post(
    "/alert/webhook",
    status_code=status.HTTP_202_ACCEPTED,
    dependencies=[Depends(require_alert_webhook_token)],
)
async def webhook(payload: AlertWebhookPayload, background: BackgroundTasks):
    logger.info("Received alert webhook %s", json.dumps(payload.dict(), sort_keys=True))
    background.add_task(deliver_ops_alert_payload, payload)
