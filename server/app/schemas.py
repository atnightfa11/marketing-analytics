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
    plan: Literal["free", "standard", "pro"] = "free"


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
    success_url: str | None = None
    cancel_url: str | None = None


class CheckoutSessionResponse(BaseModel):
    checkout_url: str
    session_id: str


class BillingStatusResponse(BaseModel):
    site_id: str
    plan: Literal["free", "standard", "pro"]
    has_subscription: bool


class SdkBootstrapRequest(BaseModel):
    site_key: str = Field(min_length=12)
    site_id: str | None = None


class SdkBootstrapConfig(BaseModel):
    site_id: str
    sampling_rate: float
    epsilon_budget: float
    shuffle_url: str
    token_ttl_seconds: int


class SdkBootstrapResponse(BaseModel):
    upload_token: str
    expires_at: dt.datetime
    config: SdkBootstrapConfig


class SdkInstallVerifyResponse(BaseModel):
    site_id: str
    lookback_minutes: int
    has_recent_activity: bool
    recent_reports: int
    counts_by_kind: dict[str, int]
    last_report_at: dt.datetime | None = None


class AuthStatusResponse(BaseModel):
    enabled: bool


class AuthLoginRequest(BaseModel):
    username: str
    password: str


class AuthLoginResponse(BaseModel):
    access_token: str
    token_type: Literal["bearer"] = "bearer"
    expires_at: dt.datetime


class AuthMeResponse(BaseModel):
    username: str


class DashboardSiteSummary(BaseModel):
    site_id: str
    site_name: str
    allowed_origin: str
    plan: Literal["free", "standard", "pro"] = "free"


class DashboardSitesResponse(BaseModel):
    sites: list[DashboardSiteSummary]


class PublicSignupRequest(BaseModel):
    username: str = Field(min_length=3, max_length=64)
    email: str = Field(min_length=5, max_length=255)
    password: str = Field(min_length=8, max_length=128)
    site_name: str = Field(min_length=1, max_length=255)
    site_domain: str = Field(min_length=3, max_length=255)
    plan: Literal["free", "standard"] = "free"


class PublicSignupResponse(BaseModel):
    username: str
    access_token: str
    token_type: Literal["bearer"] = "bearer"
    expires_at: dt.datetime
    site_id: str
    site_name: str
    site_domain: str
    site_key: str
    checkout_url: str | None = None
    requires_checkout: bool = False


class PrivatizedEvent(BaseModel):
    site_id: str
    kind: Literal["uniques", "pageviews", "sessions", "conversions", "revenue"]
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


class HistoricalImportRow(BaseModel):
    day: dt.date
    metric: Literal["uniques", "pageviews", "sessions", "conversions", "revenue"]
    value: float = Field(ge=0)


class HistoricalImportRequest(BaseModel):
    site_id: str
    rows: list[HistoricalImportRow]
    allow_live_overlap: bool = False


class HistoricalImportResponse(BaseModel):
    site_id: str
    imported_rows: int
    reduced_days: int
    batch_id: int | None = None


class HistoricalCsvImportRequest(BaseModel):
    site_id: str
    csv_text: str
    allow_live_overlap: bool = False


class HistoricalImportPreviewOverlap(BaseModel):
    day: dt.date
    metric: str
    source: Literal["live", "historical_import"]
    count: int


class HistoricalImportPreviewResponse(BaseModel):
    site_id: str
    valid: bool
    row_count: int
    day_count: int
    start_day: dt.date | None = None
    end_day: dt.date | None = None
    metrics: list[str] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    live_overlaps: list[HistoricalImportPreviewOverlap] = Field(default_factory=list)
    replaceable_import_overlaps: list[HistoricalImportPreviewOverlap] = Field(default_factory=list)


class HistoricalImportBatchResponse(BaseModel):
    id: int
    site_id: str
    source: str
    status: str
    imported_rows: int
    reduced_days: int
    start_day: dt.date | None = None
    end_day: dt.date | None = None
    metrics: list[str] = Field(default_factory=list)
    created_by: str | None = None
    created_at: dt.datetime
    completed_at: dt.datetime | None = None
    rolled_back_at: dt.datetime | None = None
    error: str | None = None
    rollback_available: bool = False


class HistoricalImportHistoryResponse(BaseModel):
    site_id: str
    batches: list[HistoricalImportBatchResponse]


class HistoricalImportRollbackResponse(BaseModel):
    site_id: str
    batch_id: int
    status: str
    deleted_rows: int
    reduced_days: int


class SiteAccessGrantRequest(BaseModel):
    site_id: str
    username: str = Field(min_length=1, max_length=64)
    role: Literal["member"] = "member"


class SiteAccessMemberResponse(BaseModel):
    username: str
    role: Literal["owner", "member"]
    created_by: str | None = None
    created_at: dt.datetime | None = None


class SiteAccessListResponse(BaseModel):
    site_id: str
    members: list[SiteAccessMemberResponse]


class SiteIpBlockCreateRequest(BaseModel):
    site_id: str
    cidr: str = Field(min_length=1, max_length=64)
    label: str | None = Field(default=None, max_length=255)


class SiteIpBlockResponse(BaseModel):
    id: int
    site_id: str
    cidr: str
    label: str | None = None
    created_by: str | None = None
    created_at: dt.datetime


class SiteIpBlockListResponse(BaseModel):
    site_id: str
    blocks: list[SiteIpBlockResponse]


class SiteHealthCheck(BaseModel):
    key: str
    label: str
    status: Literal["ok", "warning", "error"]
    detail: str
    action: str | None = None


class SiteHealthResponse(BaseModel):
    site_id: str
    plan: Literal["free", "standard", "pro"] = "free"
    overall_status: Literal["ok", "warning", "error"]
    lookback_minutes: int
    recent_reports: int
    counts_by_kind: dict[str, int] = Field(default_factory=dict)
    last_report_at: dt.datetime | None = None
    active_site_keys: int
    detected_hostnames: list[str] = Field(default_factory=list)
    latest_reducer_status: str | None = None
    latest_reducer_day: dt.date | None = None
    latest_reduced_at: dt.datetime | None = None
    latest_standard_window_start: dt.datetime | None = None
    latest_standard_published_at: dt.datetime | None = None
    forecast_metrics_ready: list[str] = Field(default_factory=list)
    forecast_metrics_building: list[str] = Field(default_factory=list)
    checks: list[SiteHealthCheck]


class ConfidenceInterval(BaseModel):
    low: float
    high: float


class BreakdownRow(BaseModel):
    label: str
    value: float
    metrics: dict[str, float] = Field(default_factory=dict)


class BreakdownResponse(BaseModel):
    site_id: str
    dimension: Literal["pages", "sources", "devices", "countries", "conversions", "hour_of_day", "day_of_week", "hostnames"]
    total: float
    primary_metric: str
    metric_keys: list[str] = Field(default_factory=list)
    totals: dict[str, float] = Field(default_factory=dict)
    rows: list[BreakdownRow]


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
    trained_at: dt.datetime | None = None


class DashboardNoteBase(BaseModel):
    site_id: str
    day: dt.date
    body: str = Field(min_length=1, max_length=1200)
    metric: str | None = Field(default=None, max_length=64)


class DashboardNoteCreateRequest(DashboardNoteBase):
    pass


class DashboardNoteUpdateRequest(BaseModel):
    site_id: str
    day: dt.date | None = None
    body: str | None = Field(default=None, min_length=1, max_length=1200)
    metric: str | None = Field(default=None, max_length=64)


class DashboardNoteResponse(DashboardNoteBase):
    id: int
    created_by: str | None = None
    created_at: dt.datetime
    updated_at: dt.datetime


class DashboardNotesResponse(BaseModel):
    site_id: str
    notes: list[DashboardNoteResponse]


class AlertWebhookPayload(BaseModel):
    source: str
    severity: Literal["info", "warning", "critical"]
    message: str
    metadata: dict[str, Any]


class SiteAlertSettingsUpdateRequest(BaseModel):
    site_id: str
    anomaly_alerts_enabled: bool = False
    slack_enabled: bool = False
    slack_webhook_url: str | None = Field(default=None, max_length=2048)
    email_enabled: bool = False
    email_recipients: list[str] = Field(default_factory=list)


class SiteAlertSettingsResponse(BaseModel):
    site_id: str
    anomaly_alerts_enabled: bool
    slack_enabled: bool
    slack_webhook_url_set: bool
    email_enabled: bool
    email_recipients: list[str] = Field(default_factory=list)
    email_delivery_configured: bool
    updated_at: dt.datetime | None = None


class HealthResponse(BaseModel):
    status: Literal["ok"]
    checks: dict[str, bool] = Field(default_factory=dict)
    details: dict[str, Any] = Field(default_factory=dict)
