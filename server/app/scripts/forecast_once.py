from __future__ import annotations

import asyncio
import logging

from ..models import async_engine
from ..worker import run_forecast_training_once


async def main() -> None:
    logging.basicConfig(level=logging.INFO)
    await run_forecast_training_once()
    await async_engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
