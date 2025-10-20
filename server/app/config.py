from pydantic_settings import BaseSettings
from pydantic import AnyHttpUrl, Field

class Settings(BaseSettings):
    DATABASE_URL: str
    UPLOAD_TOKEN_SECRET: str
    UPLOAD_TOKEN_TTL_SECONDS: int = 900
    MIN_REPORTS_PER_WINDOW: int = 25
    LIVE_WATERMARK_SECONDS: int = 120
    MAX_OUT_OF_ORDER_SECONDS: int = 300
    RATE_LIMIT_BUCKET_PER_MIN: int = 200
    ALPHA_SMOOTHING: float = 0.5
    MAX_EVENTS_PER_MINUTE: int = 60
    ALLOWED_ORIGINS_REGEX: str = r".*"
    PROMETHEUS_ENABLED: bool = True

    class Config:
        env_file = ".env"

settings = Settings()
