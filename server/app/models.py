from __future__ import annotations

import datetime as dt
from typing import AsyncGenerator

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    JSON,
    String,
    UniqueConstraint,
    text,
)
from sqlalchemy import Identity
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

from .config import get_settings

settings = get_settings()
async_engine = create_async_engine(settings.DATABASE_URL, echo=False, future=True)
async_session_factory = async_sessionmaker(async_engine, expire_on_commit=False)
IS_POSTGRES = async_engine.url.get_backend_name().startswith("postgresql")
IDENTITY_ARGS = (Identity(),) if IS_POSTGRES else ()


class Base(DeclarativeBase):
    pass


class LdpReport(Base):
    __tablename__ = "ldp_reports"
    __table_args__ = (Index("ix_ldp_reports_site_kind_day", "site_id", "kind", "day"),)
    if IS_POSTGRES:
        __table_args__ = __table_args__ + ({"postgresql_partition_by": "RANGE (day)"},)

    id: Mapped[int] = mapped_column(
        Integer,
        *IDENTITY_ARGS,
        primary_key=True,
        autoincrement=True,
    )
    site_id: Mapped[str] = mapped_column(String, nullable=False)
    kind: Mapped[str] = mapped_column(String, nullable=False)
    day: Mapped[dt.date] = mapped_column(Date, nullable=False, primary_key=IS_POSTGRES)
    payload: Mapped[dict] = mapped_column(JSON, nullable=False)
    epsilon_used: Mapped[float] = mapped_column(Float, nullable=False)
    sampling_rate: Mapped[float] = mapped_column(Float, nullable=False)
    server_received_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("CURRENT_TIMESTAMP")
    )


class RawReport(Base):
    __tablename__ = "raw_reports"
    __table_args__ = (
        Index("ix_raw_reports_site_kind_day", "site_id", "kind", "day"),
        Index("ix_raw_reports_import_batch", "import_batch_id"),
    )

    id: Mapped[int] = mapped_column(
        Integer,
        *IDENTITY_ARGS,
        primary_key=True,
        autoincrement=True,
    )
    site_id: Mapped[str] = mapped_column(String, nullable=False)
    kind: Mapped[str] = mapped_column(String, nullable=False)
    day: Mapped[dt.date] = mapped_column(Date, nullable=False)
    payload: Mapped[dict] = mapped_column(JSON, nullable=False)
    import_batch_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    epsilon_used: Mapped[float] = mapped_column(Float, nullable=False)
    sampling_rate: Mapped[float] = mapped_column(Float, nullable=False)
    server_received_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("CURRENT_TIMESTAMP")
    )


class DpWindow(Base):
    __tablename__ = "dp_windows"
    __table_args__ = (
        UniqueConstraint("site_id", "window_start", "metric", "plan", name="uq_window"),
        Index("ix_dp_windows_site_metric", "site_id", "metric", "plan"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    site_id: Mapped[str] = mapped_column(String, nullable=False)
    plan: Mapped[str] = mapped_column(String, nullable=False, default="free")
    window_start: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    window_end: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    metric: Mapped[str] = mapped_column(String, nullable=False)
    value: Mapped[float] = mapped_column(Float, nullable=False)
    variance: Mapped[float] = mapped_column(Float, nullable=False)
    ci80_low: Mapped[float] = mapped_column(Float, nullable=False)
    ci80_high: Mapped[float] = mapped_column(Float, nullable=False)
    ci95_low: Mapped[float] = mapped_column(Float, nullable=False)
    ci95_high: Mapped[float] = mapped_column(Float, nullable=False)
    published_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("CURRENT_TIMESTAMP")
    )


class DailyUnique(Base):
    __tablename__ = "daily_uniques"
    __table_args__ = (UniqueConstraint("site_id", "day", name="uq_daily_uniques"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    site_id: Mapped[str] = mapped_column(String, nullable=False)
    day: Mapped[dt.date] = mapped_column(Date, nullable=False)
    value: Mapped[float] = mapped_column(Float, nullable=False)
    variance: Mapped[float] = mapped_column(Float, nullable=False)


class BreakdownRollup(Base):
    __tablename__ = "breakdown_rollups"
    __table_args__ = (
        UniqueConstraint(
            "site_id",
            "plan",
            "day",
            "dimension",
            "hostname",
            "day_type",
            "label",
            "metric",
            name="uq_breakdown_rollup",
        ),
        Index("ix_breakdown_rollups_lookup", "site_id", "plan", "dimension", "day"),
        Index("ix_breakdown_rollups_hostname", "site_id", "plan", "hostname", "day"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    site_id: Mapped[str] = mapped_column(String, nullable=False)
    plan: Mapped[str] = mapped_column(String, nullable=False)
    day: Mapped[dt.date] = mapped_column(Date, nullable=False)
    dimension: Mapped[str] = mapped_column(String, nullable=False)
    hostname: Mapped[str] = mapped_column(String, nullable=False, default="")
    day_type: Mapped[str] = mapped_column(String, nullable=False, default="all")
    label: Mapped[str] = mapped_column(String, nullable=False)
    metric: Mapped[str] = mapped_column(String, nullable=False)
    value: Mapped[float] = mapped_column(Float, nullable=False)
    updated_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("CURRENT_TIMESTAMP")
    )


class ReducerWatermark(Base):
    __tablename__ = "reducer_watermarks"
    __table_args__ = (
        UniqueConstraint("site_id", "plan", "day", "reducer_version", name="uq_reducer_watermark"),
        Index("ix_reducer_watermarks_status", "status", "day"),
        Index("ix_reducer_watermarks_site_day", "site_id", "day"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    site_id: Mapped[str] = mapped_column(String, nullable=False)
    plan: Mapped[str] = mapped_column(String, nullable=False)
    day: Mapped[dt.date] = mapped_column(Date, nullable=False)
    reducer_version: Mapped[str] = mapped_column(String, nullable=False)
    status: Mapped[str] = mapped_column(String, nullable=False)
    raw_report_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    dp_window_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    breakdown_rollup_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    reduced_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    raw_purged_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    error: Mapped[str | None] = mapped_column(String, nullable=True)


class Forecast(Base):
    __tablename__ = "forecasts"
    __table_args__ = (
        UniqueConstraint("site_id", "plan", "metric", "day", name="uq_forecast_site_plan_metric_day"),
        Index("ix_forecasts_site_metric_day", "site_id", "metric", "day", "plan"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    site_id: Mapped[str] = mapped_column(String, nullable=False)
    plan: Mapped[str] = mapped_column(String, nullable=False, default="free")
    metric: Mapped[str] = mapped_column(String, nullable=False)
    day: Mapped[dt.date] = mapped_column(Date, nullable=False)
    yhat: Mapped[float] = mapped_column(Float, nullable=False)
    yhat_lower: Mapped[float] = mapped_column(Float, nullable=False)
    yhat_upper: Mapped[float] = mapped_column(Float, nullable=False)
    mape: Mapped[float] = mapped_column(Float, nullable=False)
    has_anomaly: Mapped[bool] = mapped_column(Boolean, default=False)
    z_score: Mapped[float] = mapped_column(Float, default=0.0)
    trained_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    model_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("model_store.id"))

    model: Mapped["ModelStore"] = relationship("ModelStore")


class UploadToken(Base):
    __tablename__ = "upload_tokens"
    __table_args__ = (
        Index("ix_upload_tokens_site", "site_id"),
        Index("ix_upload_tokens_exp", "exp"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    site_id: Mapped[str] = mapped_column(String, nullable=False)
    jti: Mapped[str] = mapped_column(String, nullable=False, unique=True)
    token_hash: Mapped[str] = mapped_column(String, nullable=False, unique=True)
    iat: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    exp: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    allowed_origin: Mapped[str] = mapped_column(String, nullable=False)
    sampling_rate: Mapped[float] = mapped_column(Float, nullable=False)
    epsilon_budget: Mapped[float] = mapped_column(Float, nullable=False)
    revoked_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class TokenNonce(Base):
    __tablename__ = "token_nonce"
    __table_args__ = (Index("ix_token_nonce_site", "site_id"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    site_id: Mapped[str] = mapped_column(String, nullable=False)
    jti: Mapped[str] = mapped_column(String, nullable=False, unique=True)
    seen_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("CURRENT_TIMESTAMP")
    )


class SiteEpsilonLog(Base):
    __tablename__ = "site_epsilon_log"
    __table_args__ = (UniqueConstraint("site_id", "day", "plan", name="uq_site_epsilon"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    site_id: Mapped[str] = mapped_column(String, nullable=False)
    day: Mapped[dt.date] = mapped_column(Date, nullable=False)
    plan: Mapped[str] = mapped_column(String, nullable=False, default="standard")
    epsilon_total: Mapped[float] = mapped_column(Float, nullable=False)


class SiteConfig(Base):
    __tablename__ = "site_config"

    site_id: Mapped[str] = mapped_column(String, primary_key=True)
    max_events_per_minute: Mapped[int] = mapped_column(Integer, default=settings.MAX_EVENTS_PER_MINUTE)
    experimental_metrics: Mapped[bool] = mapped_column(Boolean, default=False)


class SitePlan(Base):
    __tablename__ = "site_plan"
    __table_args__ = (Index("ix_site_plan_plan", "plan"),)

    site_id: Mapped[str] = mapped_column(String, primary_key=True)
    plan: Mapped[str] = mapped_column(String, nullable=False, default="free")
    stripe_customer_id: Mapped[str | None] = mapped_column(String, nullable=True)
    stripe_subscription_id: Mapped[str | None] = mapped_column(String, nullable=True)
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("CURRENT_TIMESTAMP")
    )
    updated_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("CURRENT_TIMESTAMP")
    )


class SiteApiKey(Base):
    __tablename__ = "site_api_keys"
    __table_args__ = (
        Index("ix_site_api_keys_site_active", "site_id", "is_active"),
        Index("ix_site_api_keys_key_id", "key_id", unique=True),
        Index("ix_site_api_keys_key_prefix", "key_prefix"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    site_id: Mapped[str] = mapped_column(String, nullable=False)
    key_id: Mapped[str] = mapped_column(String(64), nullable=False)
    key_prefix: Mapped[str] = mapped_column(String(32), nullable=False)
    key_hash: Mapped[str] = mapped_column(String, nullable=False)
    allowed_origin_pattern: Mapped[str] = mapped_column(String, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("CURRENT_TIMESTAMP")
    )
    updated_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("CURRENT_TIMESTAMP")
    )


class DashboardUser(Base):
    __tablename__ = "dashboard_users"
    __table_args__ = (
        Index("ix_dashboard_users_email", "email", unique=True),
    )

    username: Mapped[str] = mapped_column(String(64), primary_key=True)
    email: Mapped[str] = mapped_column(String(255), nullable=False, unique=True)
    password_hash: Mapped[str] = mapped_column(String, nullable=False)
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("CURRENT_TIMESTAMP")
    )
    updated_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("CURRENT_TIMESTAMP")
    )


class DashboardSite(Base):
    __tablename__ = "dashboard_sites"
    __table_args__ = (
        Index("ix_dashboard_sites_owner", "owner_username"),
        Index("ix_dashboard_sites_origin", "allowed_origin"),
    )

    site_id: Mapped[str] = mapped_column(String, primary_key=True)
    owner_username: Mapped[str] = mapped_column(
        String(64), ForeignKey("dashboard_users.username"), nullable=False
    )
    site_name: Mapped[str] = mapped_column(String(255), nullable=False)
    allowed_origin: Mapped[str] = mapped_column(String(255), nullable=False)
    timezone: Mapped[str] = mapped_column(String(64), nullable=False, server_default=text("'UTC'"))
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("CURRENT_TIMESTAMP")
    )
    updated_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("CURRENT_TIMESTAMP")
    )


class DashboardSiteAccess(Base):
    __tablename__ = "dashboard_site_access"
    __table_args__ = (
        UniqueConstraint("site_id", "username", name="uq_dashboard_site_access_member"),
        Index("ix_dashboard_site_access_site", "site_id"),
        Index("ix_dashboard_site_access_username", "username"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    site_id: Mapped[str] = mapped_column(String, nullable=False)
    username: Mapped[str] = mapped_column(String(64), ForeignKey("dashboard_users.username"), nullable=False)
    role: Mapped[str] = mapped_column(String(32), nullable=False, default="member")
    created_by: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("CURRENT_TIMESTAMP")
    )


class SiteIpBlock(Base):
    __tablename__ = "site_ip_blocks"
    __table_args__ = (
        UniqueConstraint("site_id", "cidr", name="uq_site_ip_blocks_site_cidr"),
        Index("ix_site_ip_blocks_site", "site_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    site_id: Mapped[str] = mapped_column(String, nullable=False)
    cidr: Mapped[str] = mapped_column(String(64), nullable=False)
    label: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_by: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("CURRENT_TIMESTAMP")
    )


class SiteAlertSettings(Base):
    __tablename__ = "site_alert_settings"
    __table_args__ = (
        UniqueConstraint("site_id", name="uq_site_alert_settings_site"),
        Index("ix_site_alert_settings_site", "site_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    site_id: Mapped[str] = mapped_column(String, nullable=False)
    anomaly_alerts_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    slack_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    slack_webhook_url: Mapped[str | None] = mapped_column(String(2048), nullable=True)
    email_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    email_recipients: Mapped[list[str] | None] = mapped_column(JSON, nullable=True)
    created_by: Mapped[str | None] = mapped_column(String(64), nullable=True)
    updated_by: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("CURRENT_TIMESTAMP")
    )
    updated_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("CURRENT_TIMESTAMP")
    )


class SiteAlertDelivery(Base):
    __tablename__ = "site_alert_deliveries"
    __table_args__ = (
        UniqueConstraint("site_id", "metric", "channel", "anomaly_key", name="uq_site_alert_delivery"),
        Index("ix_site_alert_deliveries_site_sent", "site_id", "sent_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    site_id: Mapped[str] = mapped_column(String, nullable=False)
    metric: Mapped[str] = mapped_column(String(64), nullable=False)
    channel: Mapped[str] = mapped_column(String(32), nullable=False)
    anomaly_key: Mapped[str] = mapped_column(String(128), nullable=False)
    sent_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class SiteGoal(Base):
    __tablename__ = "site_goals"
    __table_args__ = (
        Index("ix_site_goals_site", "site_id"),
        Index(
            "uq_site_goals_site_metric_default",
            "site_id",
            "metric",
            unique=True,
            postgresql_where=text("conversion_type IS NULL"),
            sqlite_where=text("conversion_type IS NULL"),
        ),
        Index(
            "uq_site_goals_site_metric_conversion_type",
            "site_id",
            "metric",
            "conversion_type",
            unique=True,
            postgresql_where=text("conversion_type IS NOT NULL"),
            sqlite_where=text("conversion_type IS NOT NULL"),
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    site_id: Mapped[str] = mapped_column(String, nullable=False)
    metric: Mapped[str] = mapped_column(String(64), nullable=False)
    conversion_type: Mapped[str | None] = mapped_column(String(120), nullable=True)
    target: Mapped[float] = mapped_column(Float, nullable=False)
    period_days: Mapped[int] = mapped_column(Integer, nullable=False, default=30)
    repeat: Mapped[str] = mapped_column(String(32), nullable=False, default="monthly")
    created_by: Mapped[str | None] = mapped_column(String(64), nullable=True)
    updated_by: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("CURRENT_TIMESTAMP")
    )
    updated_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("CURRENT_TIMESTAMP")
    )


class DashboardNote(Base):
    __tablename__ = "dashboard_notes"
    __table_args__ = (
        Index("ix_dashboard_notes_site_day", "site_id", "day"),
        Index("ix_dashboard_notes_created", "created_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    site_id: Mapped[str] = mapped_column(String, nullable=False)
    day: Mapped[dt.date] = mapped_column(Date, nullable=False)
    body: Mapped[str] = mapped_column(String(1200), nullable=False)
    metric: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_by: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("CURRENT_TIMESTAMP")
    )
    updated_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("CURRENT_TIMESTAMP")
    )


class HistoricalImportBatch(Base):
    __tablename__ = "historical_import_batches"
    __table_args__ = (
        Index("ix_historical_import_batches_site_created", "site_id", "created_at"),
        Index("ix_historical_import_batches_site_status", "site_id", "status"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    site_id: Mapped[str] = mapped_column(String, nullable=False)
    source: Mapped[str] = mapped_column(String(64), nullable=False, default="csv")
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="pending")
    imported_rows: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    reduced_days: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    start_day: Mapped[dt.date | None] = mapped_column(Date, nullable=True)
    end_day: Mapped[dt.date | None] = mapped_column(Date, nullable=True)
    metrics: Mapped[list[str] | None] = mapped_column(JSON, nullable=True)
    created_by: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("CURRENT_TIMESTAMP")
    )
    completed_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    rolled_back_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    error: Mapped[str | None] = mapped_column(String(2000), nullable=True)


class ModelStore(Base):
    __tablename__ = "model_store"
    __table_args__ = (Index("ix_model_store_site_metric", "site_id", "engine", "metric", "plan"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    site_id: Mapped[str] = mapped_column(String, nullable=False)
    plan: Mapped[str] = mapped_column(String, nullable=False, default="free")
    engine: Mapped[str] = mapped_column(String, nullable=False)
    metric: Mapped[str] = mapped_column(String, nullable=False, default="pageviews")
    uri: Mapped[str] = mapped_column(String, nullable=False)
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("CURRENT_TIMESTAMP")
    )
    mape_cv: Mapped[float] = mapped_column(Float, nullable=False)


async def init_db() -> None:
    # Place holder for migrations - actual schema is managed via Alembic.
    return


async def get_session() -> AsyncGenerator[AsyncSession, None]:
    async with async_session_factory() as session:
        yield session
