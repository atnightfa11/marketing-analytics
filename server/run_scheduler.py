#!/usr/bin/env python3
"""
Script to run the nightly reduce scheduler
"""
import asyncio
import sys
import os
import argparse

# Add the current directory to Python path so we can import app modules
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app.scheduler.nightly_reduce import reduce_reports
from app.models import async_session_factory

async def main():
    """Run the nightly reduce process"""
    parser = argparse.ArgumentParser(description="Run nightly reducer")
    parser.add_argument("--days", type=int, default=1, help="Reprocess last N days")
    args = parser.parse_args()
    print("Running nightly reduce scheduler...")

    # Create a session and run the reduce process
    async with async_session_factory() as session:
        await reduce_reports(session, days=max(1, args.days))

    print("Nightly reduce completed successfully!")

if __name__ == "__main__":
    asyncio.run(main())
