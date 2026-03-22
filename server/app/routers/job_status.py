from __future__ import annotations

from fastapi import APIRouter

from ..job_status import JOB_STATUS

router = APIRouter(tags=["jobs"])


@router.get("/jobs/status")
async def jobs_status():
    return {"jobs": JOB_STATUS}
