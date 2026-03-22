from __future__ import annotations

import datetime as dt
from typing import Any

JOB_STATUS: dict[str, dict[str, Any]] = {
    "reduce": {"last_run_at": None, "last_success_at": None, "last_error": None},
    "forecast": {"last_run_at": None, "last_success_at": None, "last_error": None},
}


def mark_job_run(name: str) -> None:
    JOB_STATUS.setdefault(name, {})
    JOB_STATUS[name]["last_run_at"] = dt.datetime.now(dt.timezone.utc).isoformat()


def mark_job_success(name: str) -> None:
    JOB_STATUS.setdefault(name, {})
    JOB_STATUS[name]["last_success_at"] = dt.datetime.now(dt.timezone.utc).isoformat()
    JOB_STATUS[name]["last_error"] = None


def mark_job_error(name: str, err: Exception) -> None:
    JOB_STATUS.setdefault(name, {})
    JOB_STATUS[name]["last_error"] = str(err)
