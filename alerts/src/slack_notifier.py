import asyncio
import json
import logging
from pathlib import Path
from typing import Any, Dict

import httpx

logger = logging.getLogger("alerts.slack")
logging.basicConfig(level=logging.INFO)

SLACK_WEBHOOK_URL = "https://hooks.slack.com/services/placeholder"
DEAD_LETTER_PATH = Path("/app/data/dead_letter.jsonl")
DEAD_LETTER_PATH.parent.mkdir(parents=True, exist_ok=True)


async def notify(alert: Dict[str, Any]) -> None:
  payload = {
      "text": f"[{alert['severity'].upper()}] {alert['message']}",
      "blocks": [
          {
              "type": "section",
              "text": {
                  "type": "mrkdwn",
                  "text": f"*Source*: {alert['source']}\n*Severity*: {alert['severity']}\n```{json.dumps(alert['metadata'], indent=2)}```",
              },
          }
      ],
  }
  backoff = 1
  for attempt in range(5):
    try:
      async with httpx.AsyncClient(timeout=10.0) as client:
        response = await client.post(SLACK_WEBHOOK_URL, json=payload)
        response.raise_for_status()
        logger.info("Alert delivered to Slack")
        return
    except Exception as exc:  # noqa: BLE001
      logger.warning("Slack delivery failed (%s), retrying...", exc)
      await asyncio.sleep(backoff)
      backoff *= 2
  with DEAD_LETTER_PATH.open("a", encoding="utf-8") as handle:
    handle.write(json.dumps(alert) + "\n")


async def main():
  while True:
    # This sidecar expects POST /notify from the API; here we idle.
    await asyncio.sleep(60)


if __name__ == "__main__":
  asyncio.run(main())
