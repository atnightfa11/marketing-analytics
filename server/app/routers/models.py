# Async SQLAlchemy models for core tables, including token hash and nonce
from sqlalchemy.orm import declarative_base, Mapped, mapped_column
from sqlalchemy import String, Integer, Float, JSON, Text, DateTime, Index
from sqlalchemy.dialects.postgresql import JSONB
from datetime import datetime, timezone
import hashlib

Base = declarative_base()

def now_utc() -> datetime:
    return datetime.now(timezone.utc)

class LdpReport(Base):
    __tablename__ = "ldp_reports"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    site_id: Mapped[str] = mapped_column(String(64), index=True, nullable=False)
    kind: Mapped[str] = mapped_column(String(32), nullable=False)
    day: Mapped[str] = mapped_column(String(10), index=True, nullable=False)  # YYYY-MM-DD
    payload: Mapped[dict] = mapped_column(JSONB, nullable=False)
    epsilon_used: Mapped[float] = mapped_column(Float, nullable=False)
    sampling_rate: Mapped[float] = mapped_column(Float, default=1.0, nullable=False)
    server_received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc, index=True)

    __table_args__ = (
        Index("idx_reports_site_day", "site_id", "day"),
    )

class DpWindow(Base):
    __tablename__ = "dp_windows"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    site_id: Mapped[str] = mapped_column(String(64), index=True, nullable=False)
    window_start: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True, nullable=False)
    window_end: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True, nullable=False)
    metric: Mapped[str] = mapped_column(String(32), index=True, nullable=False)
    value: Mapped[float] = mapped_column(Float, nullable=False)
    variance: Mapped[float] = mapped_column(Float, nullable=False)
    ci80_low: Mapped[float] = mapped_column(Float, nullable=True)
    ci80_high: Mapped[float] = mapped_column(Float, nullable=True)
    ci95_low: Mapped[float] = mapped_column(Float, nullable=True)
    ci95_high: Mapped[float] = mapped_column(Float, nullable=True)
    published_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)

class DailyUnique(Base):
    __tablename__ = "dp_uniques_daily"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    site_id: Mapped[str] = mapped_column(String(64), index=True, nullable=False)
    day: Mapped[str] = mapped_column(String(10), index=True, nullable=False)
    value: Mapped[float] = mapped_column(Float, nullable=False)
    variance: Mapped[float] = mapped_column(Float, nullable=False)

class Forecast(Base):
    __tablename__ = "forecasts"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    site_id: Mapped[str] = mapped_column(String(64), index=True, nullable=False)
    metric: Mapped[str] = mapped_column(String(32), index=True, nullable=False)
    day: Mapped[str] = mapped_column(String(10), index=True, nullable=False)
    yhat: Mapped[float] = mapped_column(Float, nullable=False)
    yhat_lower: Mapped[float] = mapped_column(Float, nullable=False)
    yhat_upper: Mapped[float] = mapped_column(Float, nullable=False)
    mape: Mapped[float] = mapped_column(Float, nullable=True)
    has_anomaly: Mapped[bool] = mapped_column(nullable=False, default=False)
    z_score: Mapped[float] = mapped_column(Float, nullable=True)
    model_id: Mapped[str] = mapped_column(String(64), nullable=True)

class UploadToken(Base):
    __tablename__ = "upload_tokens"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    site_id: Mapped[str] = mapped_column(String(64), index=True, nullable=False)
    token_hash: Mapped[str] = mapped_column(String(128), nullable=False)
    iat: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)
    exp: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

class TokenNonce(Base):
    __tablename__ = "token_nonce"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    site_id: Mapped[str] = mapped_column(String(64), index=True, nullable=False)
    jti: Mapped[str] = mapped_column(String(64), index=True, nullable=False)
    seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)

class SiteEpsilonLog(Base):
    __tablename__ = "site_epsilon_log"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    site_id: Mapped[str] = mapped_column(String(64), index=True, nullable=False)
    day: Mapped[str] = mapped_column(String(10), index=True, nullable=False)
    epsilon_total: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)

class SiteConfig(Base):
    __tablename__ = "site_config"
    site_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    max_events_per_minute: Mapped[int] = mapped_column(Integer, default=60, nullable=False)
    experimental_metrics: Mapped[bool] = mapped_column(nullable=False, default=False)
