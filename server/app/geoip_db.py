from __future__ import annotations

import datetime as dt
import gzip
import logging
from pathlib import Path

import httpx

from .config import Settings

logger = logging.getLogger(__name__)


def _expand_geoip_url_template(raw_url: str, now: dt.datetime) -> str:
    return (
        raw_url.replace("{year_month}", now.strftime("%Y-%m"))
        .replace("{year}", now.strftime("%Y"))
        .replace("{month}", now.strftime("%m"))
    )


def _decompress_if_needed(content: bytes) -> bytes:
    # GZIP magic number
    if len(content) >= 2 and content[0] == 0x1F and content[1] == 0x8B:
        return gzip.decompress(content)
    return content


def _download_geoip_bytes(url: str, timeout_seconds: int) -> bytes:
    with httpx.Client(timeout=max(5, timeout_seconds), follow_redirects=True) as client:
        response = client.get(url)
        response.raise_for_status()
        return response.content


def _write_geoip_db(target_path: Path, content: bytes) -> None:
    target_path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = target_path.with_suffix(target_path.suffix + ".tmp")
    tmp_path.write_bytes(content)
    tmp_path.replace(target_path)


def ensure_geoip_database(settings: Settings) -> str | None:
    existing_path = settings.GEOIP_COUNTRY_DB_PATH
    if existing_path and Path(existing_path).is_file():
        return existing_path

    raw_url = settings.GEOIP_COUNTRY_DB_URL
    if not raw_url:
        return existing_path

    target_path = Path(existing_path or "/tmp/geoip-country.mmdb")
    now = dt.datetime.now(dt.timezone.utc)
    current_url = _expand_geoip_url_template(raw_url, now)
    fallback_url = _expand_geoip_url_template(raw_url, now - dt.timedelta(days=32))
    candidates = [current_url]
    if fallback_url != current_url:
        candidates.append(fallback_url)

    timeout_seconds = settings.GEOIP_COUNTRY_DB_DOWNLOAD_TIMEOUT_SECONDS
    for candidate in candidates:
        try:
            content = _download_geoip_bytes(candidate, timeout_seconds=timeout_seconds)
            content = _decompress_if_needed(content)
            _write_geoip_db(target_path, content)
            settings.GEOIP_COUNTRY_DB_PATH = str(target_path)
            logger.info("GeoIP database ready", extra={"path": str(target_path), "source_url": candidate})
            return str(target_path)
        except Exception:
            logger.exception("Failed GeoIP database download attempt", extra={"source_url": candidate})

    return existing_path

