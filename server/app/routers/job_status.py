from __future__ import annotations

from fastapi import APIRouter, Depends

from ..dashboard_auth import require_dashboard_auth
from ..job_status import JOB_STATUS

router = APIRouter(tags=["jobs"])


@router.get("/jobs/status")
async def jobs_status(_auth_claims: dict | None = Depends(require_dashboard_auth)):
    return {"jobs": JOB_STATUS}
