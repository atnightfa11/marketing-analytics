"""Measured engagement shared by site KPIs and filtered reports."""
from __future__ import annotations

import datetime as dt

INTERACTIVE_KINDS = frozenset({"pageviews", "conversions", "revenue"})


def engagement_totals(
    events: list[tuple[dt.datetime, str]], *, max_gap_seconds: int,
) -> tuple[int, float, float]:
    """Measure first-to-last interaction, without inventing time after exit."""
    ordered = sorted((timestamp, kind) for timestamp, kind in events if kind in INTERACTIVE_KINDS)
    sessions = 0
    bounces = duration = 0.0
    current: list[tuple[dt.datetime, str]] = []

    def finish() -> None:
        nonlocal sessions, bounces, duration
        if not current:
            return
        sessions += 1
        pageviews = sum(kind == "pageviews" for _, kind in current)
        converted = any(kind in {"conversions", "revenue"} for _, kind in current)
        bounces += float(pageviews == 1 and not converted)
        duration += (current[-1][0] - current[0][0]).total_seconds()

    for event in ordered:
        if current and (event[0] - current[-1][0]).total_seconds() > max_gap_seconds:
            finish()
            current = []
        current.append(event)
    finish()
    return sessions, bounces, duration
