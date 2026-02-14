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
    __table_args__ = (Index("ix_raw_reports_site_kind_day", "site_id", "kind", "day"),)

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


class Forecast(Base):
    __tablename__ = "forecasts"
    __table_args__ = (Index("ix_forecasts_site_metric_day", "site_id", "metric", "day", "plan"),)

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
    model_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("model_store.id"))

    model: Mapped["ModelStore"] = relationship("ModelStore")


class UploadToken(Base):
    __tablename__ = "upload_tokens"
    __table_args__ = (Index("ix_upload_tokens_site", "site_id"),)

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
