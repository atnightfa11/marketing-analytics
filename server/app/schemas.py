from __future__ import annotations

import datetime as dt
from typing import Any, Literal

from pydantic import BaseModel, Field, validator


class UploadTokenRequest(BaseModel):
    site_id: str
    allowed_origin: str
    epsilon_budget: float = Field(gt=0)
    sampling_rate: float = Field(ge=0, le=1)
    ttl_seconds: int | None = Field(default=None, ge=60, le=3600)


class UploadTokenResponse(BaseModel):
    token: str
    expires_at: dt.datetime
    jti: str


class RevokeTokenRequest(BaseModel):
    jti: str | None = None
    token_hash: str | None = None

    @validator("jti", "token_hash", always=True)
    def check_one(cls, v, values):
        if not (v or values.get("jti") or values.get("token_hash")):
            raise ValueError("Provide jti or token_hash")
        return v


class RevokeTokensRequest(BaseModel):
    site_id: str


class CheckoutSessionRequest(BaseModel):
    site_id: str
    plan: Literal["standard", "pro"]


class CheckoutSessionResponse(BaseModel):
    checkout_url: str
    session_id: str


class PrivatizedEvent(BaseModel):
    site_id: str
    kind: Literal["uniques", "pageviews", "sessions", "conversions"]
    payload: dict[str, Any]
    epsilon_used: float
    sampling_rate: float
    client_timestamp: dt.datetime


class ShuffleRequest(BaseModel):
    token: str
    nonce: str
    batch: list[PrivatizedEvent]


class CollectRequest(BaseModel):
    site_id: str
    server_received_at: dt.datetime
    reports: list[PrivatizedEvent]


class ConfidenceInterval(BaseModel):
    low: float
    high: float


class MetricStatistic(BaseModel):
    metric: str
    value: float
    variance: float
    standard_error: float
    snr: float
    published_at: dt.datetime | None = None
    ci80: ConfidenceInterval
    ci95: ConfidenceInterval
    has_anomaly: bool = False


class MetricsResponse(BaseModel):
    site_id: str
    metrics: list[MetricStatistic]


class WindowAggregate(BaseModel):
    window_start: dt.datetime
    window_end: dt.datetime
    value: float
    variance: float
    ci80: ConfidenceInterval
    ci95: ConfidenceInterval


class AggregateResponse(BaseModel):
    site_id: str
    metric: str
    windows: list[WindowAggregate]


class ForecastPoint(BaseModel):
    day: dt.date
    yhat: float
    yhat_lower: float
    yhat_upper: float


class ForecastResponse(BaseModel):
    site_id: str
    metric: str
    forecast: list[ForecastPoint]
    mape: float
    has_anomaly: bool
    z_score: float


class AlertWebhookPayload(BaseModel):
    source: str
    severity: Literal["info", "warning", "critical"]
    message: str
    metadata: dict[str, Any]


class HealthResponse(BaseModel):
    status: Literal["ok"]
