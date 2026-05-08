from __future__ import annotations

from functools import lru_cache
from pydantic import BaseModel, Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
  DATABASE_URL: str = Field(default="sqlite+aiosqlite:///./marketing.db")
  UPLOAD_TOKEN_SECRET: str = Field(default="change-me")
  STRIPE_SECRET_KEY: str | None = None
  STRIPE_WEBHOOK_SECRET: str | None = None
  STRIPE_STANDARD_PRICE_ID: str | None = None
  STRIPE_PRO_PRICE_ID: str | None = None
  STRIPE_CHECKOUT_SUCCESS_URL: str = Field(default="https://app.validanalytics.io/billing/success")
  STRIPE_CHECKOUT_CANCEL_URL: str = Field(default="https://app.validanalytics.io/billing/cancel")
  STRIPE_SIGNUP_SUCCESS_URL: str = Field(default="https://validanalytics.io/signup/complete")
  STRIPE_SIGNUP_CANCEL_URL: str = Field(default="https://validanalytics.io/signup")
  UPLOAD_TOKEN_TTL_SECONDS: int = Field(default=900)
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
  SESSION_HMAC_IP_PREFIX_V4: int = Field(default=24)
  SESSION_HMAC_IP_PREFIX_V6: int = Field(default=56)
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
  ENABLE_PROD_SCHEDULER: bool = Field(default=False)
  PROD_SCHEDULER_HOUR_UTC: int = Field(default=2)
  PROD_REDUCER_INTERVAL_MINUTES: int = Field(default=60)
  MODEL_ARTIFACT_BUCKET: str | None = None
  DASHBOARD_AUTH_ENABLED: bool = Field(default=False)
  DASHBOARD_AUTH_USERNAME: str = Field(default="admin")
  DASHBOARD_AUTH_PASSWORD: str | None = None
  DASHBOARD_AUTH_USERS_JSON: str | None = None
  DASHBOARD_AUTH_SECRET: str | None = None
  DASHBOARD_AUTH_TTL_SECONDS: int = Field(default=8 * 60 * 60)
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
  cors_origin_regex: str | None = None

  model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

  @model_validator(mode="after")
  def ensure_required_cors_origins(self):
    if self.UPLOAD_TOKEN_SECRET == "change-me":
      raise ValueError("UPLOAD_TOKEN_SECRET must be overridden from the insecure default")

    if self.cors_origins_csv:
      extras = [item.strip() for item in self.cors_origins_csv.split(",") if item.strip()]
      self.cors_origins = [*self.cors_origins, *extras]

    required = ("https://app.validanalytics.io", "https://validanalytics.io")
    normalized = [origin.rstrip("/") for origin in self.cors_origins if origin]
    seen = set(normalized)
    for origin in required:
      if origin not in seen:
        normalized.append(origin)
        seen.add(origin)
    self.cors_origins = normalized
    return self


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
