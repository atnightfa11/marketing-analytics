from __future__ import annotations

from functools import lru_cache
from pydantic import BaseModel, Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
  DATABASE_URL: str = Field(default="sqlite+aiosqlite:///./marketing.db")
  UPLOAD_TOKEN_SECRET: str = Field(default="change-me")
  APP_ENV: str = Field(default="development")
  BILLING_ENABLED: bool = Field(default=False)
  STRIPE_SECRET_KEY: str | None = None
  STRIPE_WEBHOOK_SECRET: str | None = None
  STRIPE_STANDARD_PRICE_ID: str | None = None
  STRIPE_PRO_PRICE_ID: str | None = None
  STRIPE_CHECKOUT_SUCCESS_URL: str = Field(default="https://app.validanalytics.io/billing/success")
  STRIPE_CHECKOUT_CANCEL_URL: str = Field(default="https://app.validanalytics.io/billing/cancel")
  STRIPE_SIGNUP_SUCCESS_URL: str = Field(default="https://validanalytics.io/signup/complete")
  STRIPE_SIGNUP_CANCEL_URL: str = Field(default="https://validanalytics.io/signup")
  UPLOAD_TOKEN_TTL_SECONDS: int = Field(default=900)
  UPLOAD_TOKEN_PURGE_GRACE_SECONDS: int = Field(default=24 * 60 * 60)
  UPLOAD_TOKEN_PURGE_INTERVAL_SECONDS: int = Field(default=5 * 60)
  MIN_REPORTS_PER_WINDOW: int = Field(default=40)
  LIVE_WATERMARK_SECONDS: int = Field(default=120)
  MAX_OUT_OF_ORDER_SECONDS: int = Field(default=300)
  RATE_LIMIT_BUCKET_PER_MIN: int = Field(default=200)
  ALPHA_SMOOTHING: float = Field(default=0.5)
  MAX_EVENTS_PER_MINUTE: int = Field(default=60)
  AGGREGATE_DP_EPSILON: float = Field(default=1.0)
  AGGREGATE_DP_NOISE_SECRET: str | None = None
  ENABLE_PRO_INGEST: bool = Field(default=False)
  SESSION_HMAC_SECRET: str | None = None
  SESSION_WINDOW_MINUTES: int = Field(default=30)
  SESSION_HMAC_IP_PREFIX_V4: int = Field(default=32)
  SESSION_HMAC_IP_PREFIX_V6: int = Field(default=64)
  BOT_FILTER_ENABLED: bool = Field(default=True)
  BOT_FILTER_MIN_CF_SCORE: int = Field(default=30)
  BOT_FILTER_UA_PATTERNS_CSV: str | None = None
  GEOIP_COUNTRY_DB_PATH: str | None = None
  GEOIP_COUNTRY_DB_URL: str | None = None
  GEOIP_COUNTRY_DB_DOWNLOAD_TIMEOUT_SECONDS: int = Field(default=20)
  SDK_BOOTSTRAP_RATE_LIMIT_PER_MINUTE: int = Field(default=60)
  SDK_SITE_KEY_PREFIX: str = Field(default="vsk")
  SDK_ALLOW_WILDCARD_ORIGIN_KEYS: bool = Field(default=False)
  ADMIN_API_TOKEN: str | None = None
  COLLECT_ENDPOINT_TOKEN: str | None = None
  FREE_RATE_LIMIT_BUCKET_PER_MIN: int = Field(default=60)
  STANDARD_RATE_LIMIT_BUCKET_PER_MIN: int = Field(default=240)
  FORECAST_HORIZON_DAYS: int = Field(default=90)
  ALERT_EMAIL_SMTP_HOST: str | None = None
  ALERT_EMAIL_SMTP_PORT: int = Field(default=587)
  ALERT_EMAIL_SMTP_USERNAME: str | None = None
  ALERT_EMAIL_SMTP_PASSWORD: str | None = None
  ALERT_EMAIL_FROM: str | None = None
  ALERT_EMAIL_USE_TLS: bool = Field(default=True)
  ALERT_WEBHOOK_TOKEN: str | None = None
  ALERT_SIDECAR_URL: str = Field(default="http://alerts:8080/notify")
  LOGIN_RATE_LIMIT_PER_MINUTE: int = Field(default=10)
  # In production the schema is owned by Alembic migrations. Leave this False so the
  # service never silently diverges from migrations via create_all; enable only for
  # local/dev/test bootstrapping.
  AUTO_CREATE_DB_SCHEMA: bool = Field(default=False)
  ENABLE_PROD_SCHEDULER: bool = Field(default=False)
  PROD_SCHEDULER_HOUR_UTC: int = Field(default=2)
  PROD_REDUCER_INTERVAL_MINUTES: int = Field(default=60)
  RAW_REPORT_PURGE_ENABLED: bool = Field(default=True)
  FREE_RAW_PURGE_ENABLED: bool = Field(default=False)
  RAW_REPORT_RETENTION_HOURS: int = Field(default=72)
  MODEL_ARTIFACT_BUCKET: str | None = None
  SHUFFLE_MAX_DELAY_SECONDS: int = Field(default=120)
  DASHBOARD_AUTH_ENABLED: bool = Field(default=True)
  DASHBOARD_AUTH_USERNAME: str = Field(default="admin")
  DASHBOARD_AUTH_PASSWORD: str | None = None
  DASHBOARD_AUTH_USERS_JSON: str | None = None
  DASHBOARD_AUTH_ALLOW_PLAINTEXT_DEV: bool = Field(default=False)
  DASHBOARD_AUTH_SECRET: str | None = None
  DASHBOARD_AUTH_TTL_SECONDS: int = Field(default=8 * 60 * 60)
  DASHBOARD_AUTH_COOKIE_NAME: str = Field(default="valid_dashboard_session")
  DASHBOARD_AUTH_COOKIE_SECURE: bool | None = Field(default=None)
  DASHBOARD_AUTH_COOKIE_SAMESITE: str = Field(default="lax")
  DASHBOARD_CORS_ORIGINS: list[str] = Field(
      default_factory=lambda: [
          "https://app.validanalytics.io",
          "https://validanalytics.io",
          "https://dashboard.localdp.example.com",
          "http://localhost:5173",
          "http://127.0.0.1:5173",
      ]
  )
  DASHBOARD_CORS_ORIGINS_CSV: str | None = None
  DASHBOARD_ALLOWED_SITE_IDS: str | None = None
  DASHBOARD_SITE_ACCESS_JSON: str | None = None
  DASHBOARD_ALLOW_UNCLAIMED_SITES: bool = Field(default=False)
  expose_docs: bool = False
  cors_origins: list[str] = Field(
      default_factory=lambda: [
          "https://app.validanalytics.io",
          "https://validanalytics.io",
          "https://dashboard.localdp.example.com",
          "http://localhost:5173",
          "http://127.0.0.1:5173",
      ]
  )
  csp_policy: str = Field(
      default="default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:;"
  )
  cors_origins_csv: str | None = None
  cors_allow_all: bool = False
  # Public SDK/browser ingest runs on customer-owned domains.
  # Keep CORS broad for browser clients while endpoint-level token/origin checks
  # still enforce site-level authorization.
  cors_origin_regex: str | None = Field(
      default=r"^https?://.*$"
  )

  model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

  @model_validator(mode="after")
  def ensure_required_cors_origins(self):
    if self.UPLOAD_TOKEN_SECRET == "change-me":
      raise ValueError("UPLOAD_TOKEN_SECRET must be overridden from the insecure default")
    if self.DASHBOARD_AUTH_ENABLED and not self.DASHBOARD_AUTH_SECRET:
      raise ValueError("DASHBOARD_AUTH_SECRET must be configured when dashboard auth is enabled")
    if self.BILLING_ENABLED:
      missing_billing = [
          name
          for name, value in (
              ("STRIPE_SECRET_KEY", self.STRIPE_SECRET_KEY),
              ("STRIPE_WEBHOOK_SECRET", self.STRIPE_WEBHOOK_SECRET),
              ("STRIPE_STANDARD_PRICE_ID", self.STRIPE_STANDARD_PRICE_ID),
          )
          if not value
      ]
      if missing_billing:
        raise ValueError(
            "Billing is enabled but required Stripe config is missing: " + ", ".join(missing_billing)
        )
    production_like = self.APP_ENV.strip().lower() in {"prod", "production"}
    if production_like and not self.DASHBOARD_AUTH_ENABLED:
      raise ValueError("DASHBOARD_AUTH_ENABLED cannot be disabled in production")
    if production_like and self.DASHBOARD_AUTH_ALLOW_PLAINTEXT_DEV:
      raise ValueError("DASHBOARD_AUTH_ALLOW_PLAINTEXT_DEV cannot be enabled in production")
    if self.DASHBOARD_AUTH_COOKIE_SAMESITE.lower() not in {"lax", "strict", "none"}:
      raise ValueError("DASHBOARD_AUTH_COOKIE_SAMESITE must be lax, strict, or none")
    if self.DASHBOARD_AUTH_COOKIE_SAMESITE.lower() == "none":
      cookie_secure = self.DASHBOARD_AUTH_COOKIE_SECURE if self.DASHBOARD_AUTH_COOKIE_SECURE is not None else production_like
      if not cookie_secure:
        raise ValueError("DASHBOARD_AUTH_COOKIE_SAMESITE=none requires a Secure cookie")
    if self.SHUFFLE_MAX_DELAY_SECONDS < 0:
      raise ValueError("SHUFFLE_MAX_DELAY_SECONDS cannot be negative")

    if self.cors_origins_csv:
      extras = [item.strip() for item in self.cors_origins_csv.split(",") if item.strip()]
      self.cors_origins = [*self.cors_origins, *extras]
    if self.DASHBOARD_CORS_ORIGINS_CSV:
      extras = [item.strip() for item in self.DASHBOARD_CORS_ORIGINS_CSV.split(",") if item.strip()]
      self.DASHBOARD_CORS_ORIGINS = [*self.DASHBOARD_CORS_ORIGINS, *extras]

    required = ("https://app.validanalytics.io", "https://validanalytics.io")
    normalized = [origin.rstrip("/") for origin in self.cors_origins if origin]
    seen = set(normalized)
    for origin in required:
      if origin not in seen:
        normalized.append(origin)
        seen.add(origin)
    self.cors_origins = normalized

    dashboard_normalized = [origin.rstrip("/") for origin in self.DASHBOARD_CORS_ORIGINS if origin]
    dashboard_seen = set(dashboard_normalized)
    for origin in required:
      if origin not in dashboard_seen:
        dashboard_normalized.append(origin)
        dashboard_seen.add(origin)
    self.DASHBOARD_CORS_ORIGINS = dashboard_normalized
    return self

  def billing_configured(self) -> bool:
    return bool(self.STRIPE_SECRET_KEY and self.STRIPE_WEBHOOK_SECRET and self.STRIPE_STANDARD_PRICE_ID)

  def auth_configured(self) -> bool:
    return (not self.DASHBOARD_AUTH_ENABLED) or bool(self.DASHBOARD_AUTH_SECRET)

  def alert_email_configured(self) -> bool:
    return bool(self.ALERT_EMAIL_SMTP_HOST and self.ALERT_EMAIL_FROM)


@lru_cache(1)
def get_settings() -> Settings:
  return Settings()


class TokenClaims(BaseModel):
  site_id: str
  plan: str = "free"
  allowed_origin: str
  iat: int
  exp: int
  jti: str
  sampling_rate: float
  epsilon_budget: float
