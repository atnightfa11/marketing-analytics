#!/usr/bin/env python3
"""
Script to run the nightly reduce scheduler
"""
import asyncio
import sys
import os

# Add the current directory to Python path so we can import app modules
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app.scheduler.nightly_reduce import reduce_reports
from app.models import async_session_factory

async def main():
    """Run the nightly reduce process"""
    print("Running nightly reduce scheduler...")

    # Create a session and run the reduce process
    async with async_session_factory() as session:
        await reduce_reports(session)

    print("Nightly reduce completed successfully!")

if __name__ == "__main__":
    asyncio.run(main())
