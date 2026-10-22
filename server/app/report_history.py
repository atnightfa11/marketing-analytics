"""Select one published version of a site/day, independently of billing access."""
from sqlalchemy import func, select
from sqlalchemy.orm import aliased

from .models import DpWindow, ReducerWatermark
from .sql_dates import utc_report_day


def published_plan_clause(model, entitlement_plan: str):
    if entitlement_plan == "pro":
        return model.plan == "pro"
    day = model.day if hasattr(model, "day") else utc_report_day(model.window_start)
    watermark = aliased(ReducerWatermark)
    window = aliased(DpWindow)
    published = (
        select(watermark.plan)
        .where(
            watermark.site_id == model.site_id,
            watermark.day == day,
            watermark.status == "success",
            watermark.plan.in_(("free", "standard")),
        )
        .order_by(watermark.reduced_at.desc(), watermark.id.desc())
        .limit(1)
        .correlate(model)
        .scalar_subquery()
    )
    # Legacy windows predate watermarks. Choose one whole day's version, never
    # sum copies from both plans or use the customer's current subscription.
    legacy = (
        select(window.plan)
        .where(
            window.site_id == model.site_id,
            utc_report_day(window.window_start) == day,
            window.plan.in_(("free", "standard")),
        )
        .order_by(window.published_at.desc(), window.plan.desc(), window.id.desc())
        .limit(1)
        .correlate(model)
        .scalar_subquery()
    )
    return model.plan == func.coalesce(published, legacy, entitlement_plan)
