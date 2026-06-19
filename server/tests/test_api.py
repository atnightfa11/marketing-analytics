import asyncio
import os
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from starlette.requests import Request

# Add the parent directory to Python path so we can import the app module
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

TEST_DB_PATH = Path(__file__).parent / "test.db"
os.environ["DATABASE_URL"] = f"sqlite+aiosqlite:///{TEST_DB_PATH}"
os.environ["UPLOAD_TOKEN_SECRET"] = "test-upload-token-secret"
os.environ["SESSION_HMAC_SECRET"] = "test-session-hmac-secret"
os.environ["ADMIN_API_TOKEN"] = "test-admin-api-token"
os.environ["COLLECT_ENDPOINT_TOKEN"] = "test-collect-token"
os.environ["DASHBOARD_AUTH_ENABLED"] = "false"
os.environ["DASHBOARD_AUTH_SECRET"] = "test-dashboard-auth-secret"
os.environ["DASHBOARD_AUTH_ALLOW_PLAINTEXT_DEV"] = "true"
os.environ["SHUFFLE_MAX_DELAY_SECONDS"] = "0"
os.environ["AUTO_CREATE_DB_SCHEMA"] = "true"
os.environ["ALERT_WEBHOOK_TOKEN"] = "test-alert-token"
# Effectively disable login throttling for the suite (many tests log in repeatedly
# from the same TestClient IP). A dedicated test lowers this to verify the limiter.
os.environ["LOGIN_RATE_LIMIT_PER_MINUTE"] = "100000"
# Keep the suite hermetic: never inherit real Stripe/billing config from a local .env,
# otherwise billing-gated tests pass or fail depending on the working directory. Tests
# that exercise billing set their own Stripe config (and restore it) per-test.
os.environ["BILLING_ENABLED"] = "false"
os.environ["STRIPE_SECRET_KEY"] = ""
os.environ["STRIPE_WEBHOOK_SECRET"] = ""
os.environ["STRIPE_STANDARD_PRICE_ID"] = ""
os.environ["STRIPE_PRO_PRICE_ID"] = ""

ADMIN_HEADERS = {"X-Admin-Token": os.environ["ADMIN_API_TOKEN"]}
COLLECT_HEADERS = {"X-Collect-Token": os.environ["COLLECT_ENDPOINT_TOKEN"]}

from app.main import app  # noqa: E402
from sqlalchemy import select  # noqa: E402

from argon2 import PasswordHasher  # noqa: E402

from app.config import Settings  # noqa: E402
from app.models import Base, BreakdownRollup, DashboardNote, DashboardSite, DashboardSiteAccess, DashboardUser, DpWindow, Forecast, HistoricalImportBatch, IS_POSTGRES, LdpReport, RawReport, ReducerWatermark, SiteAlertSettings, SiteApiKey, SiteGoal, SiteIpBlock, SitePlan, UploadToken, async_engine, async_session_factory  # noqa: E402
from app.dashboard_auth import settings as dashboard_auth_settings  # noqa: E402
from app import dashboard_auth as dashboard_auth_module  # noqa: E402
from app.maintenance import purge_expired_upload_tokens, settings as maintenance_settings  # noqa: E402
from app.routers import shuffle as shuffle_router  # noqa: E402
from app.routers.aggregates import settings as aggregate_settings  # noqa: E402
from app.routers.shuffle import _derive_country_code, _derive_timezone_hint, derive_daily_visitor_key, derive_standard_session_key, resolve_client_ip  # noqa: E402
from app.geoip_db import ensure_geoip_database  # noqa: E402
from app.scheduler.nightly_reduce import reduce_reports, settings as reduce_settings  # noqa: E402
from app.scheduler.prophet_job import _forecast_fit_frame, _forecast_horizon_frame, _non_negative_forecast_interval, _with_anomaly_flags  # noqa: E402
from app.routers.upload_token import sign_claims  # noqa: E402


async def _prepare_database() -> None:
    assert not IS_POSTGRES, "Tests expect sqlite database"
    if TEST_DB_PATH.exists():
        TEST_DB_PATH.unlink()
    table = Base.metadata.tables["ldp_reports"]
    pk_cols = list(table.primary_key.columns.keys())
    assert pk_cols == ["id"], f"Unexpected ldp_reports PK columns: {pk_cols}"
    async with async_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


async def _set_site_plan(site_id: str, plan: str) -> None:
    async with async_session_factory() as session:
        record = await session.get(SitePlan, site_id)
        if record:
            record.plan = plan
        else:
            session.add(SitePlan(site_id=site_id, plan=plan))
        await session.commit()


async def _count_reports(site_id: str) -> tuple[int, int]:
    async with async_session_factory() as session:
        raw_count = len((await session.execute(select(RawReport).where(RawReport.site_id == site_id))).scalars().all())
        ldp_count = len((await session.execute(select(LdpReport).where(LdpReport.site_id == site_id))).scalars().all())
        return raw_count, ldp_count


async def _create_site_api_key(site_id: str, key_id: str, full_key: str, allowed_origin: str, active: bool = True) -> None:
    async with async_session_factory() as session:
        session.add(
            SiteApiKey(
                site_id=site_id,
                key_id=key_id,
                key_prefix=f"vsk_{key_id}",
                key_hash=PasswordHasher().hash(full_key),
                allowed_origin_pattern=allowed_origin,
                is_active=active,
            )
        )
        await session.commit()


async def _insert_dp_window(
    *,
    site_id: str,
    plan: str,
    metric: str,
    value: float,
    variance: float = 1.0,
    window_start: datetime | None = None,
) -> None:
    start = (window_start or datetime.now(timezone.utc)).replace(second=0, microsecond=0)
    minutes = 3 if metric == "uniques" else 15
    end = start + timedelta(minutes=minutes)
    ci80_half = 1.2816
    ci95_half = 1.9599
    async with async_session_factory() as session:
        existing = (
            await session.execute(
                select(DpWindow).where(
                    DpWindow.site_id == site_id,
                    DpWindow.plan == plan,
                    DpWindow.metric == metric,
                    DpWindow.window_start == start,
                )
            )
        ).scalar_one_or_none()
        if existing:
            existing.window_end = end
            existing.value = value
            existing.variance = variance
            existing.ci80_low = max(0.0, value - ci80_half)
            existing.ci80_high = max(0.0, value + ci80_half)
            existing.ci95_low = max(0.0, value - ci95_half)
            existing.ci95_high = max(0.0, value + ci95_half)
        else:
            session.add(
                DpWindow(
                    site_id=site_id,
                    plan=plan,
                    metric=metric,
                    window_start=start,
                    window_end=end,
                    value=value,
                    variance=variance,
                    ci80_low=max(0.0, value - ci80_half),
                    ci80_high=max(0.0, value + ci80_half),
                    ci95_low=max(0.0, value - ci95_half),
                    ci95_high=max(0.0, value + ci95_half),
                )
            )
        await session.commit()


async def _insert_raw_report(
    *,
    site_id: str,
    kind: str,
    payload: dict,
    day: date | None = None,
    server_received_at: datetime | None = None,
) -> None:
    received_at = (server_received_at or datetime.now(timezone.utc)).replace(microsecond=0)
    async with async_session_factory() as session:
        session.add(
            RawReport(
                site_id=site_id,
                kind=kind,
                day=day or received_at.date(),
                payload=payload,
                epsilon_used=1.0,
                sampling_rate=1.0,
                server_received_at=received_at,
            )
        )
        await session.commit()


@pytest.fixture(scope="session", autouse=True)
def setup_database():
    asyncio.run(_prepare_database())
    yield
    asyncio.run(async_engine.dispose())
    TEST_DB_PATH.unlink(missing_ok=True)


@pytest.fixture(scope="session")
def client():
    with TestClient(app) as test_client:
        yield test_client


def test_production_settings_fail_closed():
    with pytest.raises(ValueError, match="DASHBOARD_AUTH_ENABLED"):
        Settings(
            _env_file=None,
            UPLOAD_TOKEN_SECRET="test-upload-token-secret",
            APP_ENV="production",
            DASHBOARD_AUTH_ENABLED=False,
            DASHBOARD_AUTH_SECRET="test-dashboard-auth-secret",
        )

    with pytest.raises(ValueError, match="DASHBOARD_AUTH_ALLOW_PLAINTEXT_DEV"):
        Settings(
            _env_file=None,
            UPLOAD_TOKEN_SECRET="test-upload-token-secret",
            APP_ENV="production",
            DASHBOARD_AUTH_ENABLED=True,
            DASHBOARD_AUTH_SECRET="test-dashboard-auth-secret",
            DASHBOARD_AUTH_ALLOW_PLAINTEXT_DEV=True,
        )

    with pytest.raises(ValueError, match="required Stripe config"):
        Settings(
            _env_file=None,
            UPLOAD_TOKEN_SECRET="test-upload-token-secret",
            APP_ENV="production",
            DASHBOARD_AUTH_ENABLED=True,
            DASHBOARD_AUTH_SECRET="test-dashboard-auth-secret",
            BILLING_ENABLED=True,
        )


@pytest.mark.asyncio
async def test_token_issue_and_revoke(client):
    response = client.post(
        "/api/upload-token",
        json={
            "site_id": "site-a",
            "allowed_origin": "https://example.com",
            "epsilon_budget": 1.0,
            "sampling_rate": 0.5,
        },
        headers=ADMIN_HEADERS,
    )
    assert response.status_code == 200
    token = response.json()["token"]
    jti = response.json()["jti"]

    revoke = client.post("/api/admin/revoke-token", json={"jti": jti}, headers=ADMIN_HEADERS)
    assert revoke.status_code == 204

    shuffle = client.post(
        "/api/shuffle",
        json={
            "token": token,
            "nonce": "nonce-invalid",
            "batch": [],
        },
        headers={"Origin": "https://example.com"},
    )
    assert shuffle.status_code == 401


@pytest.mark.asyncio
async def test_shuffle_rejects_tampered_upload_token(client):
    token_resp = client.post(
        "/api/upload-token",
        json={
            "site_id": "site-token-tamper",
            "allowed_origin": "https://example.com",
            "epsilon_budget": 1.0,
            "sampling_rate": 1.0,
        },
        headers=ADMIN_HEADERS,
    )
    assert token_resp.status_code == 200
    token = token_resp.json()["token"]
    serialized, signature = token.split(".", 1)
    replacement = "A" if signature[0] != "A" else "B"
    tampered = f"{serialized}.{replacement}{signature[1:]}"

    shuffle = client.post(
        "/api/shuffle",
        json={"token": tampered, "nonce": "nonce-tampered-token", "batch": []},
        headers={"Origin": "https://example.com"},
    )
    assert shuffle.status_code == 401
    assert shuffle.json()["detail"] == "Invalid token"


@pytest.mark.asyncio
async def test_shuffle_rejects_signed_but_unregistered_upload_token(client):
    now = datetime.now(timezone.utc)
    token = sign_claims(
        {
            "site_id": "site-token-unregistered",
            "plan": "free",
            "allowed_origin": "https://example.com",
            "iat": int(now.timestamp()),
            "exp": int((now + timedelta(minutes=15)).timestamp()),
            "jti": "unregistered-jti",
            "sampling_rate": 1.0,
            "epsilon_budget": 1.0,
        }
    )

    shuffle = client.post(
        "/api/shuffle",
        json={"token": token, "nonce": "nonce-unregistered-token", "batch": []},
        headers={"Origin": "https://example.com"},
    )
    assert shuffle.status_code == 401
    assert shuffle.json()["detail"] == "Token not registered"


@pytest.mark.asyncio
async def test_purge_expired_upload_tokens_keeps_recent_and_active_tokens():
    now = datetime.now(timezone.utc).replace(microsecond=0)
    original_grace_seconds = maintenance_settings.UPLOAD_TOKEN_PURGE_GRACE_SECONDS
    maintenance_settings.UPLOAD_TOKEN_PURGE_GRACE_SECONDS = 24 * 60 * 60
    hasher = PasswordHasher()
    try:
        async with async_session_factory() as session:
            session.add_all(
                [
                    UploadToken(
                        site_id="site-purge",
                        jti="purge-old-expired",
                        token_hash=hasher.hash("purge-old-expired-token"),
                        iat=now - timedelta(days=3),
                        exp=now - timedelta(days=2),
                        allowed_origin="https://example.com",
                        sampling_rate=1.0,
                        epsilon_budget=1.0,
                    ),
                    UploadToken(
                        site_id="site-purge",
                        jti="purge-recent-expired",
                        token_hash=hasher.hash("purge-recent-expired-token"),
                        iat=now - timedelta(hours=2),
                        exp=now - timedelta(hours=1),
                        allowed_origin="https://example.com",
                        sampling_rate=1.0,
                        epsilon_budget=1.0,
                    ),
                    UploadToken(
                        site_id="site-purge",
                        jti="purge-active",
                        token_hash=hasher.hash("purge-active-token"),
                        iat=now,
                        exp=now + timedelta(minutes=15),
                        allowed_origin="https://example.com",
                        sampling_rate=1.0,
                        epsilon_budget=1.0,
                    ),
                ]
            )
            await session.commit()

            deleted = await purge_expired_upload_tokens(session, now=now)
            remaining = {
                token.jti
                for token in (
                    await session.execute(
                        select(UploadToken).where(UploadToken.site_id == "site-purge")
                    )
                ).scalars()
            }

        assert deleted == 1
        assert remaining == {"purge-recent-expired", "purge-active"}
    finally:
        maintenance_settings.UPLOAD_TOKEN_PURGE_GRACE_SECONDS = original_grace_seconds


@pytest.mark.asyncio
async def test_nonce_replay_rejected(client):
    token_resp = client.post(
        "/api/upload-token",
        json={
            "site_id": "site-a",
            "allowed_origin": "https://example.com",
            "epsilon_budget": 1.0,
            "sampling_rate": 1.0,
        },
        headers=ADMIN_HEADERS,
    )
    token = token_resp.json()["token"]

    batch = [
        {
            "site_id": "site-a",
            "kind": "pageviews",
            "payload": {"randomized_bit": 1, "probability_true": 0.6, "probability_false": 0.4, "variance": 0.24},
            "epsilon_used": 0.5,
            "sampling_rate": 1.0,
            "client_timestamp": datetime.now(timezone.utc).isoformat(),
        }
    ]
    first = client.post(
        "/api/shuffle",
        json={"token": token, "nonce": "same-nonce", "batch": batch},
        headers={"Origin": "https://example.com"},
    )
    assert first.status_code == 202
    second = client.post(
        "/api/shuffle",
        json={"token": token, "nonce": "same-nonce", "batch": batch},
        headers={"Origin": "https://example.com"},
    )
    assert second.status_code in (401, 409)


@pytest.mark.asyncio
async def test_shuffle_requires_origin_header(client):
    token_resp = client.post(
        "/api/upload-token",
        json={
            "site_id": "site-origin-required",
            "allowed_origin": "https://example.com",
            "epsilon_budget": 1.0,
            "sampling_rate": 1.0,
        },
        headers=ADMIN_HEADERS,
    )
    token = token_resp.json()["token"]

    batch = [
        {
            "site_id": "site-origin-required",
            "kind": "pageviews",
            "payload": {"randomized_bit": 1},
            "epsilon_used": 0.1,
            "sampling_rate": 1.0,
            "client_timestamp": datetime.now(timezone.utc).isoformat(),
        }
    ]
    resp = client.post(
        "/api/shuffle",
        json={"token": token, "nonce": "nonce-origin-required", "batch": batch},
    )
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_stale_payload_rejected(client):
    token_resp = client.post(
        "/api/upload-token",
        json={
            "site_id": "site-b",
            "allowed_origin": "https://example.com",
            "epsilon_budget": 1.0,
            "sampling_rate": 1.0,
        },
        headers=ADMIN_HEADERS,
    )
    token = token_resp.json()["token"]
    stale_ts = (datetime.now(timezone.utc) - timedelta(minutes=10)).isoformat()
    batch = [
        {
            "site_id": "site-b",
            "kind": "pageviews",
            "payload": {"randomized_bit": 1, "probability_true": 0.6, "probability_false": 0.4, "variance": 0.24},
            "epsilon_used": 0.5,
            "sampling_rate": 1.0,
            "client_timestamp": stale_ts,
        }
    ]
    resp = client.post(
        "/api/shuffle",
        json={"token": token, "nonce": "fresh-nonce", "batch": batch},
        headers={"Origin": "https://example.com"},
    )
    assert resp.status_code == 202  # accepted but dropped internally


@pytest.mark.asyncio
async def test_forecast_requires_history(client):
    response = client.get("/api/forecast/pageviews", params={"site_id": "missing"})
    assert response.status_code == 204


@pytest.mark.asyncio
async def test_forecast_response_clamps_stored_negative_values(client):
    site_id = "site-negative-forecast"
    await _set_site_plan(site_id, "standard")

    async with async_session_factory() as session:
        session.add(
            Forecast(
                site_id=site_id,
                plan="standard",
                metric="pageviews",
                day=date(2026, 6, 15),
                yhat=12.0,
                yhat_lower=-8.0,
                yhat_upper=20.0,
                mape=0.1,
                has_anomaly=False,
                z_score=0.0,
                trained_at=datetime.now(timezone.utc),
            )
        )
        await session.commit()

    response = client.get("/api/forecast/pageviews", params={"site_id": site_id})

    assert response.status_code == 200
    assert response.json()["forecast"] == [
        {"day": "2026-06-15", "yhat": 12.0, "yhat_lower": 0.0, "yhat_upper": 20.0}
    ]


@pytest.mark.asyncio
async def test_forecast_response_hides_stale_or_untrained_forecasts(client):
    site_id = "site-stale-forecast"
    await _set_site_plan(site_id, "standard")
    old_trained_at = datetime.now(timezone.utc) - timedelta(days=3)

    async with async_session_factory() as session:
        session.add_all(
            [
                Forecast(
                    site_id=site_id,
                    plan="standard",
                    metric="pageviews",
                    day=date(2026, 6, 15),
                    yhat=12.0,
                    yhat_lower=10.0,
                    yhat_upper=14.0,
                    mape=0.1,
                    has_anomaly=False,
                    z_score=0.0,
                    trained_at=None,
                ),
                Forecast(
                    site_id=site_id,
                    plan="standard",
                    metric="sessions",
                    day=date(2026, 6, 15),
                    yhat=8.0,
                    yhat_lower=6.0,
                    yhat_upper=10.0,
                    mape=0.1,
                    has_anomaly=False,
                    z_score=0.0,
                    trained_at=old_trained_at,
                ),
            ]
        )
        await session.commit()

    untrained = client.get("/api/forecast/pageviews", params={"site_id": site_id})
    stale = client.get("/api/forecast/sessions", params={"site_id": site_id})

    assert untrained.status_code == 204
    assert stale.status_code == 204


def test_non_negative_forecast_interval_preserves_valid_bounds():
    assert _non_negative_forecast_interval(12.0, -8.0, 20.0) == (12.0, 0.0, 20.0)
    assert _non_negative_forecast_interval(-5.0, -10.0, -1.0) == (0.0, 0.0, 0.0)
    assert _non_negative_forecast_interval(5.0, 8.0, 3.0) == (5.0, 5.0, 5.0)


def test_forecast_anomaly_detection_excludes_spike_from_fit():
    import pandas as pd

    start = date(2026, 1, 1)
    rows = [{"ds": start + timedelta(days=offset), "y": 100.0} for offset in range(35)]
    rows.append({"ds": start + timedelta(days=35), "y": 1200.0})

    scored = _with_anomaly_flags(pd.DataFrame(rows))
    fit = _forecast_fit_frame(scored)

    assert bool(scored.iloc[-1]["is_anomaly"]) is True
    assert scored.iloc[-1]["anomaly_z"] > 0
    assert len(fit) == len(scored) - 1
    assert fit["y"].max() == 100.0


def test_sparse_anomaly_detection_suppresses_single_count_jitter():
    import pandas as pd

    start = date(2026, 1, 1)
    sparse_history = [0.0] * 27 + [1.0]
    jitter_rows = [
        {"ds": start + timedelta(days=offset), "y": value}
        for offset, value in enumerate([*sparse_history, 1.0])
    ]
    spike_rows = [
        {"ds": start + timedelta(days=offset), "y": value}
        for offset, value in enumerate([*sparse_history, 5.0])
    ]

    jitter_scored = _with_anomaly_flags(pd.DataFrame(jitter_rows))
    spike_scored = _with_anomaly_flags(pd.DataFrame(spike_rows))

    assert bool(jitter_scored.iloc[-1]["is_anomaly"]) is False
    assert bool(spike_scored.iloc[-1]["is_anomaly"]) is True


def test_forecast_horizon_starts_after_latest_observed_day_when_latest_is_anomaly():
    import pandas as pd

    start = date(2026, 1, 1)
    rows = [{"ds": start + timedelta(days=offset), "y": 100.0} for offset in range(35)]
    rows.append({"ds": start + timedelta(days=35), "y": 1200.0})
    scored = _with_anomaly_flags(pd.DataFrame(rows))

    horizon = _forecast_horizon_frame(scored, 3)

    assert bool(scored.iloc[-1]["is_anomaly"]) is True
    assert horizon["ds"].tolist() == [
        date(2026, 2, 6),
        date(2026, 2, 7),
        date(2026, 2, 8),
    ]


@pytest.mark.asyncio
async def test_dashboard_notes_create_list_and_delete(client):
    site_id = "site-dashboard-notes"
    original_auth_enabled = dashboard_auth_settings.DASHBOARD_AUTH_ENABLED
    original_allow_unclaimed = dashboard_auth_settings.DASHBOARD_ALLOW_UNCLAIMED_SITES
    dashboard_auth_settings.DASHBOARD_AUTH_ENABLED = False
    dashboard_auth_settings.DASHBOARD_ALLOW_UNCLAIMED_SITES = True
    try:
        create_resp = client.post(
            "/api/notes",
            json={
                "site_id": site_id,
                "day": "2026-06-15",
                "metric": "pageviews",
                "body": "Heavy rain increased lake-level checks.",
            },
        )
        assert create_resp.status_code == 201
        note = create_resp.json()
        assert note["site_id"] == site_id
        assert note["day"] == "2026-06-15"
        assert note["metric"] == "pageviews"
        assert note["body"] == "Heavy rain increased lake-level checks."

        list_resp = client.get(
            "/api/notes",
            params={"site_id": site_id, "start": "2026-06-01", "end": "2026-06-30"},
        )
        assert list_resp.status_code == 200
        assert [row["id"] for row in list_resp.json()["notes"]] == [note["id"]]

        delete_resp = client.delete(f"/api/notes/{note['id']}", params={"site_id": site_id})
        assert delete_resp.status_code == 204

        async with async_session_factory() as session:
            remaining = (
                await session.execute(select(DashboardNote).where(DashboardNote.site_id == site_id))
            ).scalars().all()
        assert remaining == []
    finally:
        dashboard_auth_settings.DASHBOARD_AUTH_ENABLED = original_auth_enabled
        dashboard_auth_settings.DASHBOARD_ALLOW_UNCLAIMED_SITES = original_allow_unclaimed


@pytest.mark.asyncio
async def test_site_alert_settings_store_destinations_without_echoing_slack_secret(client):
    site_id = "site-alert-settings"
    owner = "alert-owner"
    original_auth_enabled = dashboard_auth_settings.DASHBOARD_AUTH_ENABLED
    dashboard_auth_settings.DASHBOARD_AUTH_ENABLED = False
    async with async_session_factory() as session:
        session.add(
            DashboardUser(
                username=owner,
                email="alert-owner@example.com",
                password_hash="hash",
            )
        )
        session.add(
            DashboardSite(
                site_id=site_id,
                owner_username=owner,
                site_name="Alert Settings",
                allowed_origin="https://alerts.example.com",
            )
        )
        await session.commit()

    try:
        default = client.get("/api/site-alerts", params={"site_id": site_id})
        assert default.status_code == 200
        assert default.json()["anomaly_alerts_enabled"] is False
        assert default.json()["slack_webhook_url_set"] is False

        missing_webhook = client.put(
            "/api/site-alerts",
            json={
                "site_id": site_id,
                "anomaly_alerts_enabled": True,
                "slack_enabled": True,
                "email_enabled": False,
                "email_recipients": [],
            },
        )
        assert missing_webhook.status_code == 400

        saved = client.put(
            "/api/site-alerts",
            json={
                "site_id": site_id,
                "anomaly_alerts_enabled": True,
                "slack_enabled": True,
                "slack_webhook_url": "https://hooks.slack.com/services/T000/B000/secret",
                "email_enabled": True,
                "email_recipients": ["Ops@example.com", "alerts@example.com"],
            },
        )
        assert saved.status_code == 200
        body = saved.json()
        assert body["anomaly_alerts_enabled"] is True
        assert body["slack_enabled"] is True
        assert body["slack_webhook_url_set"] is True
        assert "slack_webhook_url" not in body
        assert body["email_enabled"] is True
        assert body["email_recipients"] == ["ops@example.com", "alerts@example.com"]

        async with async_session_factory() as session:
            row = (
                await session.execute(select(SiteAlertSettings).where(SiteAlertSettings.site_id == site_id))
            ).scalar_one()
            assert row.slack_webhook_url == "https://hooks.slack.com/services/T000/B000/secret"
    finally:
        dashboard_auth_settings.DASHBOARD_AUTH_ENABLED = original_auth_enabled


@pytest.mark.asyncio
async def test_site_goals_are_owner_managed_and_update_in_place(client):
    site_id = "site-goals"
    owner = "goals-owner"
    original_auth_enabled = dashboard_auth_settings.DASHBOARD_AUTH_ENABLED
    dashboard_auth_settings.DASHBOARD_AUTH_ENABLED = False
    async with async_session_factory() as session:
        session.add(
            DashboardUser(
                username=owner,
                email="goals-owner@example.com",
                password_hash="hash",
            )
        )
        session.add(
            DashboardSite(
                site_id=site_id,
                owner_username=owner,
                site_name="Goals Site",
                allowed_origin="https://goals.example.com",
            )
        )
        await session.commit()

    try:
        empty = client.get("/api/site-goals", params={"site_id": site_id})
        assert empty.status_code == 200
        assert empty.json()["goals"] == []

        saved = client.put(
            "/api/site-goals",
            json={"site_id": site_id, "metric": "revenue", "target": 5000, "period_days": 30},
        )
        assert saved.status_code == 200
        assert saved.json()["goals"][0]["metric"] == "revenue"
        assert saved.json()["goals"][0]["target"] == 5000

        updated = client.put(
            "/api/site-goals",
            json={"site_id": site_id, "metric": "revenue", "target": 7500, "period_days": 30},
        )
        assert updated.status_code == 200
        assert updated.json()["goals"][0]["target"] == 7500

        async with async_session_factory() as session:
            rows = (
                await session.execute(
                    select(SiteGoal).where(SiteGoal.site_id == site_id, SiteGoal.metric == "revenue")
                )
            ).scalars().all()
            assert len(rows) == 1
            assert rows[0].target == 7500

        deleted = client.delete("/api/site-goals/revenue", params={"site_id": site_id})
        assert deleted.status_code == 200
        assert deleted.json()["goals"] == []
    finally:
        dashboard_auth_settings.DASHBOARD_AUTH_ENABLED = original_auth_enabled


@pytest.mark.asyncio
async def test_health_endpoints(client):
    assert client.get("/health/liveness").status_code == 200
    assert client.get("/health/readiness").status_code == 200


@pytest.mark.asyncio
async def test_plan_aware_ingest_paths(client):
    await _set_site_plan("site-free", "free")
    await _set_site_plan("site-standard", "standard")
    await _set_site_plan("site-pro", "pro")

    for site_id, plan in (("site-free", "free"), ("site-standard", "standard"), ("site-pro", "pro")):
        token_resp = client.post(
            "/api/upload-token",
            json={
                "site_id": site_id,
                "allowed_origin": "https://example.com",
                "epsilon_budget": 1.0,
                "sampling_rate": 1.0,
                "plan": plan,
            },
            headers=ADMIN_HEADERS,
        )
        token = token_resp.json()["token"]
        batch = [
            {
                "site_id": site_id,
                "kind": "pageviews",
                "payload": {"randomized_bit": 1},
                "epsilon_used": 0.1,
                "sampling_rate": 1.0,
                "client_timestamp": datetime.now(timezone.utc).isoformat(),
            }
        ]
        resp = client.post(
            "/api/shuffle",
            json={"token": token, "nonce": f"nonce-{site_id}", "batch": batch},
            headers={"Origin": "https://example.com"},
        )
        if plan == "pro":
            assert resp.status_code == 403
        else:
            assert resp.status_code == 202

    free_raw, free_ldp = await _count_reports("site-free")
    standard_raw, standard_ldp = await _count_reports("site-standard")
    assert free_raw > 0 and free_ldp == 0
    assert standard_raw > 0 and standard_ldp == 0


@pytest.mark.asyncio
async def test_privileged_endpoints_require_internal_tokens(client):
    unauth_upload = client.post(
        "/api/upload-token",
        json={
            "site_id": "site-privileged",
            "allowed_origin": "https://example.com",
            "epsilon_budget": 1.0,
            "sampling_rate": 1.0,
        },
    )
    assert unauth_upload.status_code == 401

    unauth_revoke = client.post("/api/admin/revoke-tokens", json={"site_id": "site-privileged"})
    assert unauth_revoke.status_code == 401

    collect_payload = {
        "site_id": "site-privileged",
        "server_received_at": datetime.now(timezone.utc).isoformat(),
        "reports": [],
    }
    unauth_collect = client.post("/api/collect", json=collect_payload)
    assert unauth_collect.status_code == 401

    auth_collect = client.post("/api/collect", json=collect_payload, headers=COLLECT_HEADERS)
    assert auth_collect.status_code == 202


@pytest.mark.asyncio
async def test_scheduler_smoke(client):
    async with async_session_factory() as session:
        await reduce_reports(session, days=1)


@pytest.mark.asyncio
async def test_collect_enriches_country_from_ip_lookup_and_timezone_hint(client, monkeypatch):
    monkeypatch.setattr(shuffle_router, "_lookup_country_by_ip", lambda _: "US")
    site_id = "site-geo-timezone"
    now_iso = datetime.now(timezone.utc).isoformat()
    collect_payload = {
        "site_id": site_id,
        "server_received_at": now_iso,
        "reports": [
            {
                "site_id": site_id,
                "kind": "pageviews",
                "payload": {"url": "/"},
                "epsilon_used": 0.0,
                "sampling_rate": 1.0,
                "client_timestamp": now_iso,
            }
        ],
    }
    headers = {
        **COLLECT_HEADERS,
        "X-Forwarded-For": "198.51.100.44",
        "CloudFront-Viewer-Time-Zone": "America/New_York",
        "Origin": "https://example.com",
    }
    resp = client.post("/api/collect", json=collect_payload, headers=headers)
    assert resp.status_code == 202

    async with async_session_factory() as session:
        stmt = select(RawReport).where(RawReport.site_id == site_id)
        row = (await session.execute(stmt)).scalars().first()
        assert row is not None
        assert row.payload.get("_country_code") == "US"
        assert row.payload.get("_timezone_hint") == "America/New_York"


@pytest.mark.asyncio
async def test_collect_drops_likely_bot_user_agent(client, monkeypatch):
    monkeypatch.setattr(shuffle_router.settings, "BOT_FILTER_ENABLED", True)
    site_id = "site-bot-filtered-ua"
    now_iso = datetime.now(timezone.utc).isoformat()
    collect_payload = {
        "site_id": site_id,
        "server_received_at": now_iso,
        "reports": [
            {
                "site_id": site_id,
                "kind": "pageviews",
                "payload": {"url": "/"},
                "epsilon_used": 0.0,
                "sampling_rate": 1.0,
                "client_timestamp": now_iso,
            }
        ],
    }
    headers = {
        **COLLECT_HEADERS,
        "Origin": "https://example.com",
        "User-Agent": "Mozilla/5.0 (compatible; Googlebot/2.1; +http://www.google.com/bot.html)",
    }
    resp = client.post("/api/collect", json=collect_payload, headers=headers)
    assert resp.status_code == 202

    async with async_session_factory() as session:
        stmt = select(RawReport).where(RawReport.site_id == site_id)
        assert (await session.execute(stmt)).scalars().first() is None


@pytest.mark.asyncio
async def test_collect_drops_likely_bot_by_score_header(client, monkeypatch):
    monkeypatch.setattr(shuffle_router.settings, "BOT_FILTER_ENABLED", True)
    monkeypatch.setattr(shuffle_router.settings, "BOT_FILTER_MIN_CF_SCORE", 30)
    site_id = "site-bot-filtered-score"
    now_iso = datetime.now(timezone.utc).isoformat()
    collect_payload = {
        "site_id": site_id,
        "server_received_at": now_iso,
        "reports": [
            {
                "site_id": site_id,
                "kind": "pageviews",
                "payload": {"url": "/"},
                "epsilon_used": 0.0,
                "sampling_rate": 1.0,
                "client_timestamp": now_iso,
            }
        ],
    }
    headers = {
        **COLLECT_HEADERS,
        "Origin": "https://example.com",
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_4_0)",
        "CF-Bot-Score": "1",
    }
    resp = client.post("/api/collect", json=collect_payload, headers=headers)
    assert resp.status_code == 202

    async with async_session_factory() as session:
        stmt = select(RawReport).where(RawReport.site_id == site_id)
        assert (await session.execute(stmt)).scalars().first() is None


@pytest.mark.asyncio
async def test_collect_keeps_human_traffic_when_bot_filter_enabled(client, monkeypatch):
    monkeypatch.setattr(shuffle_router.settings, "BOT_FILTER_ENABLED", True)
    site_id = "site-human-kept"
    now_iso = datetime.now(timezone.utc).isoformat()
    collect_payload = {
        "site_id": site_id,
        "server_received_at": now_iso,
        "reports": [
            {
                "site_id": site_id,
                "kind": "pageviews",
                "payload": {"url": "/"},
                "epsilon_used": 0.0,
                "sampling_rate": 1.0,
                "client_timestamp": now_iso,
            }
        ],
    }
    headers = {
        **COLLECT_HEADERS,
        "Origin": "https://example.com",
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_4_0) AppleWebKit/537.36",
    }
    resp = client.post("/api/collect", json=collect_payload, headers=headers)
    assert resp.status_code == 202

    async with async_session_factory() as session:
        stmt = select(RawReport).where(RawReport.site_id == site_id)
        row = (await session.execute(stmt)).scalars().first()
        assert row is not None


def test_standard_hmac_session_key_stability_and_rollover():
    base_time = datetime(2026, 3, 18, 12, 5, tzinfo=timezone.utc)
    stable_key_1 = derive_standard_session_key(
        site_id="site-hmac",
        server_received_at=base_time,
        ip_value="203.0.113.44",
        user_agent="Mozilla/5.0",
    )
    stable_key_2 = derive_standard_session_key(
        site_id="site-hmac",
        server_received_at=base_time + timedelta(minutes=5),
        ip_value="203.0.113.44",
        user_agent="Mozilla/5.0",
    )
    rollover_key = derive_standard_session_key(
        site_id="site-hmac",
        server_received_at=base_time + timedelta(minutes=35),
        ip_value="203.0.113.44",
        user_agent="Mozilla/5.0",
    )

    assert stable_key_1 == stable_key_2
    assert stable_key_1 != rollover_key


def test_daily_visitor_key_rotates_daily():
    base_time = datetime(2026, 3, 18, 12, 5, tzinfo=timezone.utc)
    day_key_1 = derive_daily_visitor_key(
        site_id="site-hmac",
        day=base_time.date(),
        ip_value="203.0.113.44",
        user_agent="Mozilla/5.0",
    )
    day_key_2 = derive_daily_visitor_key(
        site_id="site-hmac",
        day=base_time.date(),
        ip_value="203.0.113.44",
        user_agent="Mozilla/5.0",
    )
    next_day_key = derive_daily_visitor_key(
        site_id="site-hmac",
        day=(base_time + timedelta(days=1)).date(),
        ip_value="203.0.113.44",
        user_agent="Mozilla/5.0",
    )

    assert day_key_1 == day_key_2
    assert day_key_1 != next_day_key


def test_resolve_client_ip_prefers_proxy_headers():
    scope = {
        "type": "http",
        "http_version": "1.1",
        "method": "GET",
        "path": "/",
        "headers": [
            (b"x-forwarded-for", b"198.51.100.9, 10.0.0.2"),
            (b"cf-connecting-ip", b"203.0.113.44"),
        ],
        "client": ("172.16.0.10", 12345),
        "server": ("testserver", 80),
        "scheme": "https",
    }
    request = Request(scope)
    assert resolve_client_ip(request) == "203.0.113.44"


def test_resolve_client_ip_parses_forwarded_header_and_ipv4_port():
    scope = {
        "type": "http",
        "http_version": "1.1",
        "method": "GET",
        "path": "/",
        "headers": [
            (b"forwarded", b'for="198.51.100.22:54321";proto=https'),
        ],
        "client": ("172.16.0.10", 12345),
        "server": ("testserver", 80),
        "scheme": "https",
    }
    request = Request(scope)
    assert resolve_client_ip(request) == "198.51.100.22"


def test_derive_country_code_prefers_country_header_over_ip_lookup(monkeypatch):
    monkeypatch.setattr(shuffle_router, "_lookup_country_by_ip", lambda _: "US")
    scope = {
        "type": "http",
        "http_version": "1.1",
        "method": "GET",
        "path": "/",
        "headers": [
            (b"cf-ipcountry", b"ca"),
        ],
        "client": ("172.16.0.10", 12345),
        "server": ("testserver", 80),
        "scheme": "https",
    }
    request = Request(scope)
    assert _derive_country_code(request, client_ip="198.51.100.22") == "CA"


def test_derive_country_code_falls_back_to_ip_lookup(monkeypatch):
    captured: dict[str, str | None] = {"ip": None}

    def _fake_lookup(ip_value: str | None) -> str | None:
        captured["ip"] = ip_value
        return "GB"

    monkeypatch.setattr(shuffle_router, "_lookup_country_by_ip", _fake_lookup)
    scope = {
        "type": "http",
        "http_version": "1.1",
        "method": "GET",
        "path": "/",
        "headers": [],
        "client": ("172.16.0.10", 12345),
        "server": ("testserver", 80),
        "scheme": "https",
    }
    request = Request(scope)
    assert _derive_country_code(request, client_ip="198.51.100.55") == "GB"
    assert captured["ip"] == "198.51.100.55"


def test_derive_timezone_hint_accepts_valid_iana_headers():
    scope = {
        "type": "http",
        "http_version": "1.1",
        "method": "GET",
        "path": "/",
        "headers": [
            (b"cloudfront-viewer-time-zone", b"America/Chicago"),
        ],
        "client": ("172.16.0.10", 12345),
        "server": ("testserver", 80),
        "scheme": "https",
    }
    request = Request(scope)
    assert _derive_timezone_hint(request) == "America/Chicago"


def test_derive_timezone_hint_rejects_invalid_values():
    scope = {
        "type": "http",
        "http_version": "1.1",
        "method": "GET",
        "path": "/",
        "headers": [
            (b"x-timezone", b"Not/ARealZone"),
        ],
        "client": ("172.16.0.10", 12345),
        "server": ("testserver", 80),
        "scheme": "https",
    }
    request = Request(scope)
    assert _derive_timezone_hint(request) is None


def test_geoip_db_bootstrap_downloads_gzip_to_configured_path(monkeypatch, tmp_path):
    target = tmp_path / "geoip.mmdb"
    settings_obj = SimpleNamespace(
        GEOIP_COUNTRY_DB_PATH=str(target),
        GEOIP_COUNTRY_DB_URL="https://download.db-ip.com/free/dbip-country-lite-{year_month}.mmdb.gz",
        GEOIP_COUNTRY_DB_DOWNLOAD_TIMEOUT_SECONDS=10,
    )

    import gzip

    payload = b"fake-mmdb-content"
    gz_bytes = gzip.compress(payload)
    monkeypatch.setattr("app.geoip_db._download_geoip_bytes", lambda url, timeout_seconds: gz_bytes)

    resolved = ensure_geoip_database(settings_obj)
    assert resolved == str(target)
    assert target.read_bytes() == payload


def test_geoip_db_bootstrap_uses_existing_file_without_download(monkeypatch, tmp_path):
    target = tmp_path / "existing.mmdb"
    target.write_bytes(b"already-here")
    settings_obj = SimpleNamespace(
        GEOIP_COUNTRY_DB_PATH=str(target),
        GEOIP_COUNTRY_DB_URL="https://example.com/unused.mmdb.gz",
        GEOIP_COUNTRY_DB_DOWNLOAD_TIMEOUT_SECONDS=10,
    )

    called = {"download": False}

    def _fake_download(url: str, timeout_seconds: int) -> bytes:  # pragma: no cover - assertion below protects behavior
        called["download"] = True
        return b""

    monkeypatch.setattr("app.geoip_db._download_geoip_bytes", _fake_download)
    resolved = ensure_geoip_database(settings_obj)
    assert resolved == str(target)
    assert called["download"] is False


@pytest.mark.asyncio
async def test_standard_session_dedup_replay_resistance(client):
    await _set_site_plan("site-session-dedupe", "standard")

    token_resp = client.post(
        "/api/upload-token",
        json={
            "site_id": "site-session-dedupe",
            "allowed_origin": "https://example.com",
            "epsilon_budget": 1.0,
            "sampling_rate": 1.0,
            "plan": "standard",
        },
        headers=ADMIN_HEADERS,
    )
    token = token_resp.json()["token"]
    now_dt = datetime.now(timezone.utc)
    now_iso = now_dt.isoformat()
    payload_day = now_dt.date()
    batch = [
        {
            "site_id": "site-session-dedupe",
            "kind": "sessions",
            "payload": {"randomized_bit": 1},
            "epsilon_used": 0.1,
            "sampling_rate": 1.0,
            "client_timestamp": now_iso,
        },
        {
            "site_id": "site-session-dedupe",
            "kind": "sessions",
            "payload": {"randomized_bit": 1},
            "epsilon_used": 0.1,
            "sampling_rate": 1.0,
            "client_timestamp": now_iso,
        },
    ]

    first = client.post(
        "/api/shuffle",
        json={"token": token, "nonce": "session-dedupe-nonce", "batch": batch},
        headers={"Origin": "https://example.com"},
    )
    assert first.status_code == 202

    replay = client.post(
        "/api/shuffle",
        json={"token": token, "nonce": "session-dedupe-nonce", "batch": batch},
        headers={"Origin": "https://example.com"},
    )
    assert replay.status_code in (401, 409)

    async with async_session_factory() as session:
        original_min_reports = reduce_settings.MIN_REPORTS_PER_WINDOW
        original_epsilon = reduce_settings.AGGREGATE_DP_EPSILON
        reduce_settings.MIN_REPORTS_PER_WINDOW = 1
        reduce_settings.AGGREGATE_DP_EPSILON = 10.0
        try:
            await reduce_reports(session, start_day=payload_day, end_day=payload_day)
        finally:
            reduce_settings.MIN_REPORTS_PER_WINDOW = original_min_reports
            reduce_settings.AGGREGATE_DP_EPSILON = original_epsilon
        rows = (
            await session.execute(
                select(DpWindow).where(
                    DpWindow.site_id == "site-session-dedupe",
                    DpWindow.plan == "standard",
                    DpWindow.metric == "sessions",
                )
            )
        ).scalars().all()
        assert rows
        assert max(row.value for row in rows) <= 1.0


@pytest.mark.asyncio
async def test_standard_reducer_publishes_daily_windows_and_replaces_old_minute_rows(client):
    site_id = "site-standard-daily"
    target_day = date(2026, 5, 4)
    await _set_site_plan(site_id, "standard")
    await _insert_dp_window(
        site_id=site_id,
        plan="standard",
        metric="pageviews",
        value=99.0,
        window_start=datetime(2026, 5, 4, 12, 30, tzinfo=timezone.utc),
    )
    for minute in (5, 35, 55):
        await _insert_raw_report(
            site_id=site_id,
            kind="pageviews",
            payload={"url": "/daily"},
            day=target_day,
            server_received_at=datetime(2026, 5, 4, 12, minute, tzinfo=timezone.utc),
        )

    async with async_session_factory() as session:
        original_epsilon = reduce_settings.AGGREGATE_DP_EPSILON
        reduce_settings.AGGREGATE_DP_EPSILON = 100.0
        try:
            await reduce_reports(session, start_day=target_day, end_day=target_day)
        finally:
            reduce_settings.AGGREGATE_DP_EPSILON = original_epsilon

        rows = (
            await session.execute(
                select(DpWindow).where(
                    DpWindow.site_id == site_id,
                    DpWindow.plan == "standard",
                    DpWindow.metric == "pageviews",
                )
            )
        ).scalars().all()
        assert len(rows) == 1
        assert rows[0].window_start.replace(tzinfo=timezone.utc) == datetime(2026, 5, 4, 0, 0, tzinfo=timezone.utc)
        assert rows[0].window_end.replace(tzinfo=timezone.utc) == datetime(2026, 5, 5, 0, 0, tzinfo=timezone.utc)
        assert rows[0].value == pytest.approx(3.0, abs=0.1)


@pytest.mark.asyncio
async def test_reducer_rollups_watermark_and_raw_purge_keep_breakdowns_available(client):
    site_id = "site-rollup-purge"
    target_day = date(2026, 5, 6)
    await _set_site_plan(site_id, "standard")

    for index, session_id in enumerate(("sess-a", "sess-b", "sess-c")):
        timestamp = datetime(2026, 5, 6, 14, index, tzinfo=timezone.utc)
        await _insert_raw_report(
            site_id=site_id,
            kind="pageviews",
            payload={
                "url": "/rollup",
                "_device_bucket": "mobile",
                "_country_code": "US",
                "_session_hmac": session_id,
                "_visitor_day_hmac": f"visitor-{index}",
                "_hostname": "example.com",
            },
            day=target_day,
            server_received_at=timestamp,
        )
        await _insert_raw_report(
            site_id=site_id,
            kind="sessions",
            payload={
                "referrer_bucket": "direct",
                "_device_bucket": "mobile",
                "_country_code": "US",
                "_session_hmac": session_id,
                "_visitor_day_hmac": f"visitor-{index}",
                "_hostname": "example.com",
            },
            day=target_day,
            server_received_at=timestamp,
        )

    original_min_reports = reduce_settings.MIN_REPORTS_PER_WINDOW
    original_epsilon = reduce_settings.AGGREGATE_DP_EPSILON
    original_retention = reduce_settings.RAW_REPORT_RETENTION_HOURS
    reduce_settings.MIN_REPORTS_PER_WINDOW = 1
    reduce_settings.AGGREGATE_DP_EPSILON = 100.0
    reduce_settings.RAW_REPORT_RETENTION_HOURS = 0
    try:
        async with async_session_factory() as session:
            await reduce_reports(session, start_day=target_day, end_day=target_day)
    finally:
        reduce_settings.MIN_REPORTS_PER_WINDOW = original_min_reports
        reduce_settings.AGGREGATE_DP_EPSILON = original_epsilon
        reduce_settings.RAW_REPORT_RETENTION_HOURS = original_retention

    async with async_session_factory() as session:
        raw_rows = (
            await session.execute(select(RawReport).where(RawReport.site_id == site_id))
        ).scalars().all()
        rollup_rows = (
            await session.execute(
                select(BreakdownRollup).where(
                    BreakdownRollup.site_id == site_id,
                    BreakdownRollup.dimension == "pages",
                    BreakdownRollup.label == "/rollup",
                )
            )
        ).scalars().all()
        watermark = (
            await session.execute(select(ReducerWatermark).where(ReducerWatermark.site_id == site_id))
        ).scalars().first()

    assert raw_rows == []
    assert rollup_rows
    assert watermark is not None
    assert watermark.status == "success"
    assert watermark.raw_purged_at is not None

    response = client.get(
        "/api/breakdown",
        params={
            "site_id": site_id,
            "dimension": "pages",
            "start": target_day.isoformat(),
            "end": target_day.isoformat(),
            "limit": 10,
        },
    )
    assert response.status_code == 200
    assert response.json()["rows"] == [
        {"label": "/rollup", "value": 3.0, "metrics": {"uniques": 3.0, "sessions": 3.0, "pageviews": 3.0}}
    ]


@pytest.mark.asyncio
async def test_free_session_and_unique_dedupe_without_client_storage(client):
    await _set_site_plan("site-free-dedupe", "free")

    token_resp = client.post(
        "/api/upload-token",
        json={
            "site_id": "site-free-dedupe",
            "allowed_origin": "https://example.com",
            "epsilon_budget": 1.0,
            "sampling_rate": 1.0,
            "plan": "free",
        },
        headers=ADMIN_HEADERS,
    )
    token = token_resp.json()["token"]
    now_dt = datetime.now(timezone.utc)
    now_iso = now_dt.isoformat()
    payload_day = now_dt.date()

    batch = [
        {
            "site_id": "site-free-dedupe",
            "kind": "sessions",
            "payload": {"randomized_bit": 1, "referrer_bucket": "direct"},
            "epsilon_used": 0.1,
            "sampling_rate": 1.0,
            "client_timestamp": now_iso,
        },
        {
            "site_id": "site-free-dedupe",
            "kind": "sessions",
            "payload": {"randomized_bit": 1, "referrer_bucket": "direct"},
            "epsilon_used": 0.1,
            "sampling_rate": 1.0,
            "client_timestamp": now_iso,
        },
        {
            "site_id": "site-free-dedupe",
            "kind": "uniques",
            "payload": {"randomized_bit": 1},
            "epsilon_used": 0.1,
            "sampling_rate": 1.0,
            "client_timestamp": now_iso,
        },
        {
            "site_id": "site-free-dedupe",
            "kind": "uniques",
            "payload": {"randomized_bit": 1},
            "epsilon_used": 0.1,
            "sampling_rate": 1.0,
            "client_timestamp": now_iso,
        },
    ]

    ingest_resp = client.post(
        "/api/shuffle",
        json={"token": token, "nonce": "free-dedupe-nonce", "batch": batch},
        headers={"Origin": "https://example.com"},
    )
    assert ingest_resp.status_code == 202

    async with async_session_factory() as session:
        original_min_reports = reduce_settings.MIN_REPORTS_PER_WINDOW
        reduce_settings.MIN_REPORTS_PER_WINDOW = 1
        try:
            await reduce_reports(session, start_day=payload_day, end_day=payload_day)
        finally:
            reduce_settings.MIN_REPORTS_PER_WINDOW = original_min_reports

        session_rows = (
            await session.execute(
                select(DpWindow).where(
                    DpWindow.site_id == "site-free-dedupe",
                    DpWindow.plan == "free",
                    DpWindow.metric == "sessions",
                )
            )
        ).scalars().all()
        unique_rows = (
            await session.execute(
                select(DpWindow).where(
                    DpWindow.site_id == "site-free-dedupe",
                    DpWindow.plan == "free",
                    DpWindow.metric == "uniques",
                )
            )
        ).scalars().all()

        assert session_rows
        assert unique_rows
        assert sum(row.value for row in session_rows) == 1.0
        assert sum(row.value for row in unique_rows) == 1.0


@pytest.mark.asyncio
async def test_historical_csv_import_requires_dashboard_auth_and_standard_plan(client):
    await _set_site_plan("site-import", "free")
    old_day = (datetime.now(timezone.utc) - timedelta(days=180)).date().isoformat()

    original = (
        dashboard_auth_settings.DASHBOARD_AUTH_ENABLED,
        dashboard_auth_settings.DASHBOARD_AUTH_USERNAME,
        dashboard_auth_settings.DASHBOARD_AUTH_PASSWORD,
        dashboard_auth_settings.DASHBOARD_AUTH_USERS_JSON,
        dashboard_auth_settings.DASHBOARD_AUTH_SECRET,
        dashboard_auth_settings.DASHBOARD_AUTH_TTL_SECONDS,
        dashboard_auth_settings.DASHBOARD_ALLOWED_SITE_IDS,
        dashboard_auth_settings.DASHBOARD_SITE_ACCESS_JSON,
        dashboard_auth_settings.DASHBOARD_ALLOW_UNCLAIMED_SITES,
    )
    dashboard_auth_settings.DASHBOARD_AUTH_ENABLED = True
    dashboard_auth_settings.DASHBOARD_AUTH_USERNAME = "import-owner"
    dashboard_auth_settings.DASHBOARD_AUTH_PASSWORD = "secret-pass"
    dashboard_auth_settings.DASHBOARD_AUTH_USERS_JSON = None
    dashboard_auth_settings.DASHBOARD_AUTH_SECRET = "dashboard-auth-import-secret"
    dashboard_auth_settings.DASHBOARD_AUTH_TTL_SECONDS = 3600
    dashboard_auth_settings.DASHBOARD_ALLOWED_SITE_IDS = "site-import"
    dashboard_auth_settings.DASHBOARD_SITE_ACCESS_JSON = None
    dashboard_auth_settings.DASHBOARD_ALLOW_UNCLAIMED_SITES = False
    dashboard_auth_module._parse_auth_users.cache_clear()
    dashboard_auth_module._parse_site_access_map.cache_clear()
    try:
        unauthorized = client.post(
            "/api/import/historical-csv",
            json={"site_id": "site-import", "csv_text": f"day,metric,value\n{old_day},revenue,42\n"},
        )
        assert unauthorized.status_code == 401

        login = client.post("/api/auth/login", json={"username": "import-owner", "password": "secret-pass"})
        assert login.status_code == 200
        token = login.json()["access_token"]
        headers = {"Authorization": f"Bearer {token}"}

        blocked = client.post(
            "/api/import/historical-csv",
            json={"site_id": "site-import", "csv_text": f"day,metric,value\n{old_day},revenue,42\n"},
            headers=headers,
        )
        assert blocked.status_code == 403
        assert blocked.json()["detail"] == "Historical imports require the Standard plan"

        await _set_site_plan("site-import", "standard")
        imported = client.post(
            "/api/import/historical-csv",
            json={"site_id": "site-import", "csv_text": f"day,metric,value\n{old_day},revenue,42\n"},
            headers=headers,
        )
        assert imported.status_code == 200
        assert imported.json()["imported_rows"] == 1

        async with async_session_factory() as session:
            rows = (
                await session.execute(
                    select(DpWindow).where(
                        DpWindow.site_id == "site-import",
                        DpWindow.plan == "standard",
                        DpWindow.metric == "revenue",
                    )
                )
            ).scalars().all()
            assert rows, "Expected at least one reduced window for imported historical data"
            assert any(row.value > 0 for row in rows)
    finally:
        dashboard_auth_module._parse_auth_users.cache_clear()
        dashboard_auth_module._parse_site_access_map.cache_clear()
        (
            dashboard_auth_settings.DASHBOARD_AUTH_ENABLED,
            dashboard_auth_settings.DASHBOARD_AUTH_USERNAME,
            dashboard_auth_settings.DASHBOARD_AUTH_PASSWORD,
            dashboard_auth_settings.DASHBOARD_AUTH_USERS_JSON,
            dashboard_auth_settings.DASHBOARD_AUTH_SECRET,
            dashboard_auth_settings.DASHBOARD_AUTH_TTL_SECONDS,
            dashboard_auth_settings.DASHBOARD_ALLOWED_SITE_IDS,
            dashboard_auth_settings.DASHBOARD_SITE_ACCESS_JSON,
            dashboard_auth_settings.DASHBOARD_ALLOW_UNCLAIMED_SITES,
        ) = original


@pytest.mark.asyncio
async def test_historical_csv_import_is_idempotent_and_rejects_live_overlap(client):
    site_id = "site-import-safety"
    await _set_site_plan(site_id, "standard")
    import_day_date = (datetime.now(timezone.utc) - timedelta(days=220)).date()
    import_day = import_day_date.isoformat()
    overlap_day_date = import_day_date - timedelta(days=1)
    overlap_day = overlap_day_date.isoformat()

    original = (
        dashboard_auth_settings.DASHBOARD_AUTH_ENABLED,
        dashboard_auth_settings.DASHBOARD_AUTH_USERNAME,
        dashboard_auth_settings.DASHBOARD_AUTH_PASSWORD,
        dashboard_auth_settings.DASHBOARD_AUTH_USERS_JSON,
        dashboard_auth_settings.DASHBOARD_AUTH_SECRET,
        dashboard_auth_settings.DASHBOARD_AUTH_TTL_SECONDS,
        dashboard_auth_settings.DASHBOARD_ALLOWED_SITE_IDS,
        dashboard_auth_settings.DASHBOARD_SITE_ACCESS_JSON,
        dashboard_auth_settings.DASHBOARD_ALLOW_UNCLAIMED_SITES,
    )
    dashboard_auth_settings.DASHBOARD_AUTH_ENABLED = True
    dashboard_auth_settings.DASHBOARD_AUTH_USERNAME = "import-safety-owner"
    dashboard_auth_settings.DASHBOARD_AUTH_PASSWORD = "secret-pass"
    dashboard_auth_settings.DASHBOARD_AUTH_USERS_JSON = None
    dashboard_auth_settings.DASHBOARD_AUTH_SECRET = "dashboard-auth-import-safety-secret"
    dashboard_auth_settings.DASHBOARD_AUTH_TTL_SECONDS = 3600
    dashboard_auth_settings.DASHBOARD_ALLOWED_SITE_IDS = site_id
    dashboard_auth_settings.DASHBOARD_SITE_ACCESS_JSON = None
    dashboard_auth_settings.DASHBOARD_ALLOW_UNCLAIMED_SITES = False
    dashboard_auth_module._parse_auth_users.cache_clear()
    dashboard_auth_module._parse_site_access_map.cache_clear()
    try:
        login = client.post("/api/auth/login", json={"username": "import-safety-owner", "password": "secret-pass"})
        assert login.status_code == 200
        headers = {"Authorization": f"Bearer {login.json()['access_token']}"}

        csv_text = f"day,metric,value\n{import_day},pageviews,10\n"
        first = client.post(
            "/api/import/historical-csv",
            json={"site_id": site_id, "csv_text": csv_text},
            headers=headers,
        )
        assert first.status_code == 200
        assert first.json()["imported_rows"] == 1

        replace_preview = client.post(
            "/api/import/historical-csv/preview",
            json={"site_id": site_id, "csv_text": csv_text},
            headers=headers,
        )
        assert replace_preview.status_code == 200
        replace_payload = replace_preview.json()
        assert replace_payload["valid"] is True
        assert replace_payload["row_count"] == 1
        assert replace_payload["replaceable_import_overlaps"][0]["source"] == "historical_import"

        second = client.post(
            "/api/import/historical-csv",
            json={"site_id": site_id, "csv_text": csv_text},
            headers=headers,
        )
        assert second.status_code == 200
        assert second.json()["imported_rows"] == 1

        async with async_session_factory() as session:
            imported_rows = (
                await session.execute(
                    select(RawReport).where(
                        RawReport.site_id == site_id,
                        RawReport.day == import_day_date,
                        RawReport.kind == "pageviews",
                    )
                )
            ).scalars().all()
        historical_rows = [
            row for row in imported_rows if isinstance(row.payload, dict) and row.payload.get("historical_import")
        ]
        assert len(historical_rows) == 1
        assert historical_rows[0].payload["value"] == 10.0

        duplicate = client.post(
            "/api/import/historical-csv",
            json={"site_id": site_id, "csv_text": f"day,metric,value\n{import_day},sessions,1\n{import_day},sessions,2\n"},
            headers=headers,
        )
        assert duplicate.status_code == 400
        assert "Duplicate import row" in duplicate.json()["detail"]

        duplicate_preview = client.post(
            "/api/import/historical-csv/preview",
            json={"site_id": site_id, "csv_text": f"day,metric,value\n{import_day},sessions,1\n{import_day},sessions,2\n"},
            headers=headers,
        )
        assert duplicate_preview.status_code == 200
        assert duplicate_preview.json()["valid"] is False
        assert "Duplicate import row" in duplicate_preview.json()["errors"][0]

        await _insert_raw_report(site_id=site_id, kind="pageviews", day=overlap_day_date, payload={})
        overlap_preview = client.post(
            "/api/import/historical-csv/preview",
            json={"site_id": site_id, "csv_text": f"day,metric,value\n{overlap_day},pageviews,25\n"},
            headers=headers,
        )
        assert overlap_preview.status_code == 200
        assert overlap_preview.json()["valid"] is False
        assert overlap_preview.json()["live_overlaps"][0]["source"] == "live"
        overlap = client.post(
            "/api/import/historical-csv",
            json={
                "site_id": site_id,
                "csv_text": f"day,metric,value\n{overlap_day},pageviews,25\n",
                "allow_live_overlap": True,
            },
            headers=headers,
        )
        assert overlap.status_code == 409
        assert "overlaps existing Valid-collected data" in overlap.json()["detail"]
    finally:
        dashboard_auth_module._parse_auth_users.cache_clear()
        dashboard_auth_module._parse_site_access_map.cache_clear()
        (
            dashboard_auth_settings.DASHBOARD_AUTH_ENABLED,
            dashboard_auth_settings.DASHBOARD_AUTH_USERNAME,
            dashboard_auth_settings.DASHBOARD_AUTH_PASSWORD,
            dashboard_auth_settings.DASHBOARD_AUTH_USERS_JSON,
            dashboard_auth_settings.DASHBOARD_AUTH_SECRET,
            dashboard_auth_settings.DASHBOARD_AUTH_TTL_SECONDS,
            dashboard_auth_settings.DASHBOARD_ALLOWED_SITE_IDS,
            dashboard_auth_settings.DASHBOARD_SITE_ACCESS_JSON,
            dashboard_auth_settings.DASHBOARD_ALLOW_UNCLAIMED_SITES,
        ) = original


@pytest.mark.asyncio
async def test_historical_import_history_and_rollback(client):
    site_id = "site-import-rollback"
    await _set_site_plan(site_id, "standard")
    import_day_date = (datetime.now(timezone.utc) - timedelta(days=250)).date()
    import_day = import_day_date.isoformat()

    original = (
        dashboard_auth_settings.DASHBOARD_AUTH_ENABLED,
        dashboard_auth_settings.DASHBOARD_AUTH_USERNAME,
        dashboard_auth_settings.DASHBOARD_AUTH_PASSWORD,
        dashboard_auth_settings.DASHBOARD_AUTH_USERS_JSON,
        dashboard_auth_settings.DASHBOARD_AUTH_SECRET,
        dashboard_auth_settings.DASHBOARD_AUTH_TTL_SECONDS,
        dashboard_auth_settings.DASHBOARD_ALLOWED_SITE_IDS,
        dashboard_auth_settings.DASHBOARD_SITE_ACCESS_JSON,
        dashboard_auth_settings.DASHBOARD_ALLOW_UNCLAIMED_SITES,
    )
    dashboard_auth_settings.DASHBOARD_AUTH_ENABLED = True
    dashboard_auth_settings.DASHBOARD_AUTH_USERNAME = "rollback-owner"
    dashboard_auth_settings.DASHBOARD_AUTH_PASSWORD = "secret-pass"
    dashboard_auth_settings.DASHBOARD_AUTH_USERS_JSON = None
    dashboard_auth_settings.DASHBOARD_AUTH_SECRET = "dashboard-auth-import-rollback-secret"
    dashboard_auth_settings.DASHBOARD_AUTH_TTL_SECONDS = 3600
    dashboard_auth_settings.DASHBOARD_ALLOWED_SITE_IDS = site_id
    dashboard_auth_settings.DASHBOARD_SITE_ACCESS_JSON = None
    dashboard_auth_settings.DASHBOARD_ALLOW_UNCLAIMED_SITES = False
    dashboard_auth_module._parse_auth_users.cache_clear()
    dashboard_auth_module._parse_site_access_map.cache_clear()
    try:
        login = client.post("/api/auth/login", json={"username": "rollback-owner", "password": "secret-pass"})
        assert login.status_code == 200
        headers = {"Authorization": f"Bearer {login.json()['access_token']}"}

        imported = client.post(
            "/api/import/historical-csv",
            json={"site_id": site_id, "csv_text": f"day,metric,value\n{import_day},pageviews,100\n"},
            headers=headers,
        )
        assert imported.status_code == 200
        batch_id = imported.json()["batch_id"]
        assert isinstance(batch_id, int)

        history = client.get("/api/import/history", params={"site_id": site_id}, headers=headers)
        assert history.status_code == 200
        batches = history.json()["batches"]
        assert batches[0]["id"] == batch_id
        assert batches[0]["status"] == "completed"
        assert batches[0]["rollback_available"] is True

        async with async_session_factory() as session:
            batch = await session.get(HistoricalImportBatch, batch_id)
            assert batch is not None
            tagged_rows = (
                await session.execute(
                    select(RawReport).where(
                        RawReport.site_id == site_id,
                        RawReport.import_batch_id == batch_id,
                    )
                )
            ).scalars().all()
            assert len(tagged_rows) == 1

        rollback = client.post(
            f"/api/import/batches/{batch_id}/rollback",
            params={"site_id": site_id},
            headers=headers,
        )
        assert rollback.status_code == 200
        assert rollback.json()["deleted_rows"] == 1
        assert rollback.json()["status"] == "rolled_back"

        async with async_session_factory() as session:
            remaining_rows = (
                await session.execute(
                    select(RawReport).where(
                        RawReport.site_id == site_id,
                        RawReport.import_batch_id == batch_id,
                    )
                )
            ).scalars().all()
            assert remaining_rows == []
            day_start = datetime.combine(import_day_date, datetime.min.time(), tzinfo=timezone.utc)
            windows = (
                await session.execute(
                    select(DpWindow).where(
                        DpWindow.site_id == site_id,
                        DpWindow.plan == "standard",
                        DpWindow.metric == "pageviews",
                        DpWindow.window_start == day_start,
                    )
                )
            ).scalars().all()
            assert windows == []

        rolled_back_history = client.get("/api/import/history", params={"site_id": site_id}, headers=headers)
        assert rolled_back_history.status_code == 200
        rolled_back_batch = rolled_back_history.json()["batches"][0]
        assert rolled_back_batch["status"] == "rolled_back"
        assert rolled_back_batch["rollback_available"] is False
    finally:
        dashboard_auth_module._parse_auth_users.cache_clear()
        dashboard_auth_module._parse_site_access_map.cache_clear()
        (
            dashboard_auth_settings.DASHBOARD_AUTH_ENABLED,
            dashboard_auth_settings.DASHBOARD_AUTH_USERNAME,
            dashboard_auth_settings.DASHBOARD_AUTH_PASSWORD,
            dashboard_auth_settings.DASHBOARD_AUTH_USERS_JSON,
            dashboard_auth_settings.DASHBOARD_AUTH_SECRET,
            dashboard_auth_settings.DASHBOARD_AUTH_TTL_SECONDS,
            dashboard_auth_settings.DASHBOARD_ALLOWED_SITE_IDS,
            dashboard_auth_settings.DASHBOARD_SITE_ACCESS_JSON,
            dashboard_auth_settings.DASHBOARD_ALLOW_UNCLAIMED_SITES,
        ) = original


@pytest.mark.asyncio
async def test_site_access_membership_grants_dashboard_access(client):
    site_id = "site-shared-access"
    password_hasher = PasswordHasher()
    async with async_session_factory() as session:
        session.add_all(
            [
                DashboardUser(
                    username="owner-user",
                    email="owner-access@example.com",
                    password_hash=password_hasher.hash("owner-pass"),
                ),
                DashboardUser(
                    username="member-user",
                    email="member-access@example.com",
                    password_hash=password_hasher.hash("member-pass"),
                ),
            ]
        )
        session.add(
            DashboardSite(
                site_id=site_id,
                owner_username="owner-user",
                site_name="Shared Site",
                allowed_origin="https://shared.example.com",
                timezone="UTC",
            )
        )
        await session.commit()

    original = (
        dashboard_auth_settings.DASHBOARD_AUTH_ENABLED,
        dashboard_auth_settings.DASHBOARD_AUTH_USERNAME,
        dashboard_auth_settings.DASHBOARD_AUTH_PASSWORD,
        dashboard_auth_settings.DASHBOARD_AUTH_USERS_JSON,
        dashboard_auth_settings.DASHBOARD_AUTH_SECRET,
        dashboard_auth_settings.DASHBOARD_AUTH_TTL_SECONDS,
        dashboard_auth_settings.DASHBOARD_ALLOWED_SITE_IDS,
        dashboard_auth_settings.DASHBOARD_SITE_ACCESS_JSON,
        dashboard_auth_settings.DASHBOARD_ALLOW_UNCLAIMED_SITES,
    )
    dashboard_auth_settings.DASHBOARD_AUTH_ENABLED = True
    dashboard_auth_settings.DASHBOARD_AUTH_USERNAME = "admin"
    dashboard_auth_settings.DASHBOARD_AUTH_PASSWORD = None
    dashboard_auth_settings.DASHBOARD_AUTH_USERS_JSON = None
    dashboard_auth_settings.DASHBOARD_AUTH_SECRET = "dashboard-auth-site-access-secret"
    dashboard_auth_settings.DASHBOARD_AUTH_TTL_SECONDS = 3600
    dashboard_auth_settings.DASHBOARD_ALLOWED_SITE_IDS = None
    dashboard_auth_settings.DASHBOARD_SITE_ACCESS_JSON = None
    dashboard_auth_settings.DASHBOARD_ALLOW_UNCLAIMED_SITES = False
    dashboard_auth_module._parse_auth_users.cache_clear()
    dashboard_auth_module._parse_site_access_map.cache_clear()
    try:
        owner_login = client.post("/api/auth/login", json={"username": "owner-user", "password": "owner-pass"})
        member_login = client.post("/api/auth/login", json={"username": "member-user", "password": "member-pass"})
        assert owner_login.status_code == 200
        assert member_login.status_code == 200
        owner_headers = {"Authorization": f"Bearer {owner_login.json()['access_token']}"}
        member_headers = {"Authorization": f"Bearer {member_login.json()['access_token']}"}

        blocked = client.get("/api/site-settings", params={"site_id": site_id}, headers=member_headers)
        assert blocked.status_code == 403

        grant = client.post(
            "/api/site-access",
            json={"site_id": site_id, "username": "member-user"},
            headers=owner_headers,
        )
        assert grant.status_code == 200
        assert {member["username"] for member in grant.json()["members"]} == {"owner-user", "member-user"}

        allowed = client.get("/api/site-settings", params={"site_id": site_id}, headers=member_headers)
        assert allowed.status_code == 200

        listed = client.get("/api/sites", headers=member_headers)
        assert listed.status_code == 200
        assert site_id in {site["site_id"] for site in listed.json()["sites"]}

        member_cannot_grant = client.post(
            "/api/site-access",
            json={"site_id": site_id, "username": "owner-user"},
            headers=member_headers,
        )
        assert member_cannot_grant.status_code == 403

        revoke = client.delete(
            "/api/site-access/member-user",
            params={"site_id": site_id},
            headers=owner_headers,
        )
        assert revoke.status_code == 200
        assert {member["username"] for member in revoke.json()["members"]} == {"owner-user"}

        blocked_again = client.get("/api/site-settings", params={"site_id": site_id}, headers=member_headers)
        assert blocked_again.status_code == 403
        async with async_session_factory() as session:
            access_rows = (
                await session.execute(select(DashboardSiteAccess).where(DashboardSiteAccess.site_id == site_id))
            ).scalars().all()
            assert access_rows == []
    finally:
        dashboard_auth_module._parse_auth_users.cache_clear()
        dashboard_auth_module._parse_site_access_map.cache_clear()
        (
            dashboard_auth_settings.DASHBOARD_AUTH_ENABLED,
            dashboard_auth_settings.DASHBOARD_AUTH_USERNAME,
            dashboard_auth_settings.DASHBOARD_AUTH_PASSWORD,
            dashboard_auth_settings.DASHBOARD_AUTH_USERS_JSON,
            dashboard_auth_settings.DASHBOARD_AUTH_SECRET,
            dashboard_auth_settings.DASHBOARD_AUTH_TTL_SECONDS,
            dashboard_auth_settings.DASHBOARD_ALLOWED_SITE_IDS,
            dashboard_auth_settings.DASHBOARD_SITE_ACCESS_JSON,
            dashboard_auth_settings.DASHBOARD_ALLOW_UNCLAIMED_SITES,
        ) = original


@pytest.mark.asyncio
async def test_site_ip_blocks_can_be_managed_from_settings(client):
    site_id = "site-ip-block-settings"
    password_hasher = PasswordHasher()
    async with async_session_factory() as session:
        session.add(
            DashboardUser(
                username="ip-owner",
                email="ip-owner@example.com",
                password_hash=password_hasher.hash("owner-pass"),
            )
        )
        session.add(
            DashboardSite(
                site_id=site_id,
                owner_username="ip-owner",
                site_name="IP Block Site",
                allowed_origin="https://ip-block.example.com",
                timezone="UTC",
            )
        )
        await session.commit()

    original = (
        dashboard_auth_settings.DASHBOARD_AUTH_ENABLED,
        dashboard_auth_settings.DASHBOARD_AUTH_USERNAME,
        dashboard_auth_settings.DASHBOARD_AUTH_PASSWORD,
        dashboard_auth_settings.DASHBOARD_AUTH_USERS_JSON,
        dashboard_auth_settings.DASHBOARD_AUTH_SECRET,
        dashboard_auth_settings.DASHBOARD_AUTH_TTL_SECONDS,
        dashboard_auth_settings.DASHBOARD_ALLOWED_SITE_IDS,
        dashboard_auth_settings.DASHBOARD_SITE_ACCESS_JSON,
        dashboard_auth_settings.DASHBOARD_ALLOW_UNCLAIMED_SITES,
    )
    dashboard_auth_settings.DASHBOARD_AUTH_ENABLED = True
    dashboard_auth_settings.DASHBOARD_AUTH_USERNAME = "admin"
    dashboard_auth_settings.DASHBOARD_AUTH_PASSWORD = None
    dashboard_auth_settings.DASHBOARD_AUTH_USERS_JSON = None
    dashboard_auth_settings.DASHBOARD_AUTH_SECRET = "dashboard-auth-ip-block-secret"
    dashboard_auth_settings.DASHBOARD_AUTH_TTL_SECONDS = 3600
    dashboard_auth_settings.DASHBOARD_ALLOWED_SITE_IDS = None
    dashboard_auth_settings.DASHBOARD_SITE_ACCESS_JSON = None
    dashboard_auth_settings.DASHBOARD_ALLOW_UNCLAIMED_SITES = False
    dashboard_auth_module._parse_auth_users.cache_clear()
    dashboard_auth_module._parse_site_access_map.cache_clear()
    try:
        login = client.post("/api/auth/login", json={"username": "ip-owner", "password": "owner-pass"})
        assert login.status_code == 200
        headers = {"Authorization": f"Bearer {login.json()['access_token']}"}

        empty = client.get("/api/site-shields/ip-blocks", params={"site_id": site_id}, headers=headers)
        assert empty.status_code == 200
        assert empty.json()["blocks"] == []

        invalid = client.post(
            "/api/site-shields/ip-blocks",
            json={"site_id": site_id, "cidr": "not an ip"},
            headers=headers,
        )
        assert invalid.status_code == 400

        created = client.post(
            "/api/site-shields/ip-blocks",
            json={"site_id": site_id, "cidr": "203.0.113.10", "label": "Office"},
            headers=headers,
        )
        assert created.status_code == 200, created.text
        blocks = created.json()["blocks"]
        assert len(blocks) == 1
        assert blocks[0]["cidr"] == "203.0.113.10/32"
        assert blocks[0]["label"] == "Office"

        duplicate = client.post(
            "/api/site-shields/ip-blocks",
            json={"site_id": site_id, "cidr": "203.0.113.10/32"},
            headers=headers,
        )
        assert duplicate.status_code == 409

        deleted = client.delete(
            f"/api/site-shields/ip-blocks/{blocks[0]['id']}",
            params={"site_id": site_id},
            headers=headers,
        )
        assert deleted.status_code == 200
        assert deleted.json()["blocks"] == []
    finally:
        dashboard_auth_module._parse_auth_users.cache_clear()
        dashboard_auth_module._parse_site_access_map.cache_clear()
        (
            dashboard_auth_settings.DASHBOARD_AUTH_ENABLED,
            dashboard_auth_settings.DASHBOARD_AUTH_USERNAME,
            dashboard_auth_settings.DASHBOARD_AUTH_PASSWORD,
            dashboard_auth_settings.DASHBOARD_AUTH_USERS_JSON,
            dashboard_auth_settings.DASHBOARD_AUTH_SECRET,
            dashboard_auth_settings.DASHBOARD_AUTH_TTL_SECONDS,
            dashboard_auth_settings.DASHBOARD_ALLOWED_SITE_IDS,
            dashboard_auth_settings.DASHBOARD_SITE_ACCESS_JSON,
            dashboard_auth_settings.DASHBOARD_ALLOW_UNCLAIMED_SITES,
        ) = original


@pytest.mark.asyncio
async def test_site_ip_block_drops_matching_ingest(client):
    site_id = "site-ip-block-ingest"
    await _set_site_plan(site_id, "free")
    async with async_session_factory() as session:
        session.add(SiteIpBlock(site_id=site_id, cidr="203.0.113.0/24", label="Office"))
        await session.commit()

    token_resp = client.post(
        "/api/upload-token",
        json={
            "site_id": site_id,
            "allowed_origin": "https://example.com",
            "epsilon_budget": 1.0,
            "sampling_rate": 1.0,
        },
        headers=ADMIN_HEADERS,
    )
    assert token_resp.status_code == 200
    token = token_resp.json()["token"]
    now = datetime.now(timezone.utc).isoformat()

    accepted = client.post(
        "/api/shuffle",
        json={
            "token": token,
            "nonce": "nonce-ip-blocked",
            "batch": [
                {
                    "site_id": site_id,
                    "kind": "pageviews",
                    "payload": {"url": "/blocked"},
                    "epsilon_used": 0.5,
                    "sampling_rate": 1.0,
                    "client_timestamp": now,
                }
            ],
        },
        headers={
            "Origin": "https://example.com",
            "X-Forwarded-For": "203.0.113.25",
            "User-Agent": "Mozilla/5.0",
        },
    )
    assert accepted.status_code == 202, accepted.text
    raw_count, ldp_count = await _count_reports(site_id)
    assert raw_count == 0
    assert ldp_count == 0


@pytest.mark.asyncio
async def test_site_health_reports_tracking_reducer_and_forecast_status(client):
    site_id = "site-health-ok"
    await _set_site_plan(site_id, "standard")
    await _create_site_api_key(site_id, "healthkey", "vsk_healthkey_secretvalue", "https://health.example.com")
    now = datetime.now(timezone.utc).replace(microsecond=0)
    today = now.date()
    await _insert_raw_report(
        site_id=site_id,
        kind="pageviews",
        day=today,
        payload={"_hostname": "health.example.com"},
        server_received_at=now,
    )
    await _insert_dp_window(
        site_id=site_id,
        plan="standard",
        metric="pageviews",
        value=12,
        window_start=datetime.combine(today, datetime.min.time(), tzinfo=timezone.utc),
    )
    async with async_session_factory() as session:
        session.add(
            ReducerWatermark(
                site_id=site_id,
                plan="standard",
                day=today,
                reducer_version="rollups-v1",
                status="success",
                raw_report_count=1,
                dp_window_count=1,
                breakdown_rollup_count=0,
                reduced_at=now,
                raw_purged_at=None,
                error=None,
            )
        )
        for metric in ["pageviews", "sessions", "uniques"]:
            session.add(
                Forecast(
                    site_id=site_id,
                    plan="standard",
                    metric=metric,
                    day=today + timedelta(days=1),
                    yhat=10,
                    yhat_lower=8,
                    yhat_upper=12,
                    mape=0.2,
                    has_anomaly=False,
                    z_score=0,
                    trained_at=now,
                    model_id=None,
                )
            )
        await session.commit()

    original = (
        dashboard_auth_settings.DASHBOARD_AUTH_ENABLED,
        dashboard_auth_settings.DASHBOARD_AUTH_USERNAME,
        dashboard_auth_settings.DASHBOARD_AUTH_PASSWORD,
        dashboard_auth_settings.DASHBOARD_AUTH_USERS_JSON,
        dashboard_auth_settings.DASHBOARD_AUTH_SECRET,
        dashboard_auth_settings.DASHBOARD_AUTH_TTL_SECONDS,
        dashboard_auth_settings.DASHBOARD_ALLOWED_SITE_IDS,
        dashboard_auth_settings.DASHBOARD_SITE_ACCESS_JSON,
        dashboard_auth_settings.DASHBOARD_ALLOW_UNCLAIMED_SITES,
    )
    dashboard_auth_settings.DASHBOARD_AUTH_ENABLED = True
    dashboard_auth_settings.DASHBOARD_AUTH_USERNAME = "health-owner"
    dashboard_auth_settings.DASHBOARD_AUTH_PASSWORD = "secret-pass"
    dashboard_auth_settings.DASHBOARD_AUTH_USERS_JSON = None
    dashboard_auth_settings.DASHBOARD_AUTH_SECRET = "dashboard-auth-health-secret"
    dashboard_auth_settings.DASHBOARD_AUTH_TTL_SECONDS = 3600
    dashboard_auth_settings.DASHBOARD_ALLOWED_SITE_IDS = site_id
    dashboard_auth_settings.DASHBOARD_SITE_ACCESS_JSON = None
    dashboard_auth_settings.DASHBOARD_ALLOW_UNCLAIMED_SITES = False
    dashboard_auth_module._parse_auth_users.cache_clear()
    dashboard_auth_module._parse_site_access_map.cache_clear()
    try:
        login = client.post("/api/auth/login", json={"username": "health-owner", "password": "secret-pass"})
        assert login.status_code == 200
        headers = {"Authorization": f"Bearer {login.json()['access_token']}"}
        health = client.get("/api/site-health", params={"site_id": site_id}, headers=headers)
        assert health.status_code == 200
        body = health.json()
        assert body["overall_status"] == "ok"
        assert body["recent_reports"] == 1
        assert body["active_site_keys"] == 1
        assert body["detected_hostnames"] == ["health.example.com"]
        assert set(body["forecast_metrics_ready"]) == {"pageviews", "sessions", "uniques"}
        assert {check["key"]: check["status"] for check in body["checks"]} == {
            "api_key": "ok",
            "tracking": "ok",
            "reducer": "ok",
            "windows": "ok",
            "forecast": "ok",
        }
    finally:
        dashboard_auth_module._parse_auth_users.cache_clear()
        dashboard_auth_module._parse_site_access_map.cache_clear()
        (
            dashboard_auth_settings.DASHBOARD_AUTH_ENABLED,
            dashboard_auth_settings.DASHBOARD_AUTH_USERNAME,
            dashboard_auth_settings.DASHBOARD_AUTH_PASSWORD,
            dashboard_auth_settings.DASHBOARD_AUTH_USERS_JSON,
            dashboard_auth_settings.DASHBOARD_AUTH_SECRET,
            dashboard_auth_settings.DASHBOARD_AUTH_TTL_SECONDS,
            dashboard_auth_settings.DASHBOARD_ALLOWED_SITE_IDS,
            dashboard_auth_settings.DASHBOARD_SITE_ACCESS_JSON,
            dashboard_auth_settings.DASHBOARD_ALLOW_UNCLAIMED_SITES,
        ) = original


@pytest.mark.asyncio
async def test_sdk_bootstrap_success_and_origin_failure(client):
    await _set_site_plan("site-bootstrap", "standard")
    site_key = "vsk_bootstrapid_secretvalue"
    await _create_site_api_key("site-bootstrap", "bootstrapid", site_key, "https://example.com")

    denied = client.post(
        "/api/sdk/bootstrap",
        json={"site_key": site_key},
        headers={"Origin": "https://unrelated-example.org"},
    )
    assert denied.status_code == 403

    ok = client.post(
        "/api/sdk/bootstrap",
        json={"site_key": site_key},
        headers={"Origin": "https://example.com"},
    )
    assert ok.status_code == 200
    body = ok.json()
    assert body["upload_token"]
    assert body["config"]["site_id"] == "site-bootstrap"


@pytest.mark.asyncio
async def test_sdk_bootstrap_allows_www_and_subdomains_for_same_base_domain(client):
    await _set_site_plan("site-bootstrap-domain-scope", "free")
    site_key = "vsk_bootstrapscope_secretvalue"
    await _create_site_api_key("site-bootstrap-domain-scope", "bootstrapscope", site_key, "https://example.com")

    ok_www = client.post(
        "/api/sdk/bootstrap",
        json={"site_key": site_key},
        headers={"Origin": "https://www.example.com"},
    )
    assert ok_www.status_code == 200, ok_www.text

    ok_subdomain = client.post(
        "/api/sdk/bootstrap",
        json={"site_key": site_key},
        headers={"Origin": "https://app.example.com"},
    )
    assert ok_subdomain.status_code == 200, ok_subdomain.text


@pytest.mark.asyncio
async def test_sdk_bootstrap_www_allowed_pattern_accepts_apex_origin(client):
    await _set_site_plan("site-bootstrap-www-allowed", "free")
    site_key = "vsk_bootstrapwww_secretvalue"
    await _create_site_api_key("site-bootstrap-www-allowed", "bootstrapwww", site_key, "https://www.example.com")

    ok_apex = client.post(
        "/api/sdk/bootstrap",
        json={"site_key": site_key},
        headers={"Origin": "https://example.com"},
    )
    assert ok_apex.status_code == 200, ok_apex.text


@pytest.mark.asyncio
async def test_sdk_bootstrap_rejects_scheme_mismatch(client):
    await _set_site_plan("site-bootstrap-scheme-mismatch", "free")
    site_key = "vsk_bootstrapscheme_secretvalue"
    await _create_site_api_key("site-bootstrap-scheme-mismatch", "bootstrapscheme", site_key, "https://example.com")

    denied = client.post(
        "/api/sdk/bootstrap",
        json={"site_key": site_key},
        headers={"Origin": "http://example.com"},
    )
    assert denied.status_code == 403, denied.text


@pytest.mark.asyncio
async def test_shuffle_allows_subdomain_origin_for_apex_token(client):
    token_resp = client.post(
        "/api/upload-token",
        json={
            "site_id": "site-shuffle-domain-scope",
            "allowed_origin": "https://example.com",
            "epsilon_budget": 1.0,
            "sampling_rate": 1.0,
        },
        headers=ADMIN_HEADERS,
    )
    assert token_resp.status_code == 200, token_resp.text
    token = token_resp.json()["token"]

    batch = [
        {
            "site_id": "site-shuffle-domain-scope",
            "kind": "pageviews",
            "payload": {"randomized_bit": 1},
            "epsilon_used": 0.1,
            "sampling_rate": 1.0,
            "client_timestamp": datetime.now(timezone.utc).isoformat(),
        }
    ]
    resp = client.post(
        "/api/shuffle",
        json={"token": token, "nonce": "nonce-shuffle-domain-scope", "batch": batch},
        headers={"Origin": "https://www.example.com"},
    )
    assert resp.status_code == 202, resp.text


def test_sdk_bootstrap_preflight_allows_customer_https_origin(client):
    resp = client.options(
        "/api/sdk/bootstrap",
        headers={
            "Origin": "https://customer.example",
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "content-type",
        },
    )
    assert resp.status_code == 204
    allowed_origin = resp.headers.get("access-control-allow-origin")
    assert allowed_origin == "*"
    assert "access-control-allow-credentials" not in resp.headers
    allow_methods = (resp.headers.get("access-control-allow-methods") or "").upper()
    assert "POST" in allow_methods


def test_sdk_bootstrap_preflight_allows_customer_http_origin(client):
    resp = client.options(
        "/api/sdk/bootstrap",
        headers={
            "Origin": "http://customer.example",
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "content-type",
        },
    )
    assert resp.status_code == 204
    allowed_origin = resp.headers.get("access-control-allow-origin")
    assert allowed_origin == "*"
    assert "access-control-allow-credentials" not in resp.headers
    allow_methods = (resp.headers.get("access-control-allow-methods") or "").upper()
    assert "POST" in allow_methods


def test_dashboard_preflight_is_credentialed_only_for_trusted_origins(client):
    trusted = client.options(
        "/api/auth/login",
        headers={
            "Origin": "https://app.validanalytics.io",
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "content-type",
        },
    )
    assert trusted.status_code == 204
    assert trusted.headers.get("access-control-allow-origin") == "https://app.validanalytics.io"
    assert trusted.headers.get("access-control-allow-credentials") == "true"

    untrusted = client.options(
        "/api/auth/login",
        headers={
            "Origin": "https://evil.example",
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "content-type",
        },
    )
    assert untrusted.status_code == 400
    assert "access-control-allow-origin" not in untrusted.headers
    assert "access-control-allow-credentials" not in untrusted.headers


def test_dashboard_actual_cors_headers_are_not_reflected_for_untrusted_origins(client):
    trusted = client.get("/api/auth/status", headers={"Origin": "https://app.validanalytics.io"})
    assert trusted.status_code == 200
    assert trusted.headers.get("access-control-allow-origin") == "https://app.validanalytics.io"
    assert trusted.headers.get("access-control-allow-credentials") == "true"

    untrusted = client.get("/api/auth/status", headers={"Origin": "https://evil.example"})
    assert untrusted.status_code == 200
    assert "access-control-allow-origin" not in untrusted.headers
    assert "access-control-allow-credentials" not in untrusted.headers


def test_dashboard_mutations_reject_untrusted_browser_origins(client):
    resp = client.post("/api/auth/logout", headers={"Origin": "https://evil.example"})
    assert resp.status_code == 403
    assert resp.text == "Origin not allowed"
    assert "access-control-allow-origin" not in resp.headers


@pytest.mark.asyncio
async def test_sdk_bootstrap_rejects_site_id_mismatch(client):
    await _set_site_plan("site-bootstrap-mismatch", "standard")
    site_key = "vsk_bootstrapmismatch_secretvalue"
    await _create_site_api_key("site-bootstrap-mismatch", "bootstrapmismatch", site_key, "https://example.com")

    resp = client.post(
        "/api/sdk/bootstrap",
        json={"site_key": site_key, "site_id": "another-site"},
        headers={"Origin": "https://example.com"},
    )
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_sdk_bootstrap_rejects_inactive_site_key(client):
    await _set_site_plan("site-inactive-key", "free")
    site_key = "vsk_inactiveid_secretvalue"
    await _create_site_api_key("site-inactive-key", "inactiveid", site_key, "https://example.com", active=False)

    resp = client.post(
        "/api/sdk/bootstrap",
        json={"site_key": site_key},
        headers={"Origin": "https://example.com"},
    )
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_sdk_verify_install_returns_recent_raw_activity(client):
    site_id = "site-verify-install"
    await _set_site_plan(site_id, "free")
    now = datetime.now(timezone.utc).replace(microsecond=0)
    await _insert_raw_report(
        site_id=site_id,
        kind="pageviews",
        payload={"randomized_bit": 1},
        server_received_at=now - timedelta(minutes=2),
    )
    await _insert_raw_report(
        site_id=site_id,
        kind="sessions",
        payload={"randomized_bit": 1},
        server_received_at=now - timedelta(minutes=1),
    )

    original = (
        dashboard_auth_settings.DASHBOARD_AUTH_ENABLED,
        dashboard_auth_settings.DASHBOARD_AUTH_USERNAME,
        dashboard_auth_settings.DASHBOARD_AUTH_PASSWORD,
        dashboard_auth_settings.DASHBOARD_AUTH_USERS_JSON,
        dashboard_auth_settings.DASHBOARD_AUTH_SECRET,
        dashboard_auth_settings.DASHBOARD_AUTH_TTL_SECONDS,
        dashboard_auth_settings.DASHBOARD_ALLOWED_SITE_IDS,
        dashboard_auth_settings.DASHBOARD_SITE_ACCESS_JSON,
        dashboard_auth_settings.DASHBOARD_ALLOW_UNCLAIMED_SITES,
    )
    dashboard_auth_settings.DASHBOARD_AUTH_ENABLED = True
    dashboard_auth_settings.DASHBOARD_AUTH_USERNAME = "owner"
    dashboard_auth_settings.DASHBOARD_AUTH_PASSWORD = "secret-pass"
    dashboard_auth_settings.DASHBOARD_AUTH_USERS_JSON = None
    dashboard_auth_settings.DASHBOARD_AUTH_SECRET = "dashboard-auth-verify-install-secret"
    dashboard_auth_settings.DASHBOARD_AUTH_TTL_SECONDS = 3600
    dashboard_auth_settings.DASHBOARD_ALLOWED_SITE_IDS = site_id
    dashboard_auth_settings.DASHBOARD_SITE_ACCESS_JSON = None
    dashboard_auth_settings.DASHBOARD_ALLOW_UNCLAIMED_SITES = False
    dashboard_auth_module._parse_auth_users.cache_clear()
    dashboard_auth_module._parse_site_access_map.cache_clear()
    try:
        login = client.post("/api/auth/login", json={"username": "owner", "password": "secret-pass"})
        assert login.status_code == 200
        token = login.json()["access_token"]
        headers = {"Authorization": f"Bearer {token}"}

        resp = client.get(
            "/api/sdk/verify-install",
            params={"site_id": site_id, "lookback_minutes": 15},
            headers=headers,
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["site_id"] == site_id
        assert body["has_recent_activity"] is True
        assert body["recent_reports"] >= 2
        assert body["counts_by_kind"].get("pageviews", 0) >= 1
        assert body["counts_by_kind"].get("sessions", 0) >= 1
        assert body["last_report_at"] is not None
    finally:
        dashboard_auth_module._parse_auth_users.cache_clear()
        dashboard_auth_module._parse_site_access_map.cache_clear()
        (
            dashboard_auth_settings.DASHBOARD_AUTH_ENABLED,
            dashboard_auth_settings.DASHBOARD_AUTH_USERNAME,
            dashboard_auth_settings.DASHBOARD_AUTH_PASSWORD,
            dashboard_auth_settings.DASHBOARD_AUTH_USERS_JSON,
            dashboard_auth_settings.DASHBOARD_AUTH_SECRET,
            dashboard_auth_settings.DASHBOARD_AUTH_TTL_SECONDS,
            dashboard_auth_settings.DASHBOARD_ALLOWED_SITE_IDS,
            dashboard_auth_settings.DASHBOARD_SITE_ACCESS_JSON,
            dashboard_auth_settings.DASHBOARD_ALLOW_UNCLAIMED_SITES,
        ) = original


@pytest.mark.asyncio
async def test_metrics_and_aggregate_follow_site_plan(client):
    site_id = "site-plan-serving-contract"
    base_start = datetime(2026, 4, 11, 12, 0, tzinfo=timezone.utc)

    await _insert_dp_window(
        site_id=site_id,
        plan="free",
        metric="pageviews",
        value=10.0,
        window_start=base_start,
    )
    await _insert_dp_window(
        site_id=site_id,
        plan="free",
        metric="conversions",
        value=2.0,
        window_start=base_start,
    )
    await _insert_dp_window(
        site_id=site_id,
        plan="standard",
        metric="pageviews",
        value=100.0,
        window_start=base_start,
    )
    await _insert_dp_window(
        site_id=site_id,
        plan="standard",
        metric="conversions",
        value=25.0,
        window_start=base_start,
    )

    await _set_site_plan(site_id, "free")
    free_aggregate = client.get(
        "/api/aggregate",
        params={"site_id": site_id, "metric": "pageviews", "window": "standard"},
    )
    assert free_aggregate.status_code == 200
    free_windows = free_aggregate.json()["windows"]
    assert free_windows
    assert free_windows[0]["value"] == 10.0

    free_metrics_resp = client.get("/api/metrics", params={"site_id": site_id})
    assert free_metrics_resp.status_code == 200
    free_metrics = {row["metric"]: row for row in free_metrics_resp.json()["metrics"]}
    assert free_metrics["pageviews"]["value"] == 10.0
    assert free_metrics["conversions"]["value"] == 2.0
    assert free_metrics["conversion_rate"]["value"] == 0.2

    await _set_site_plan(site_id, "standard")
    standard_aggregate = client.get(
        "/api/aggregate",
        params={"site_id": site_id, "metric": "pageviews", "window": "standard"},
    )
    assert standard_aggregate.status_code == 200
    standard_windows = standard_aggregate.json()["windows"]
    assert standard_windows
    assert standard_windows[0]["value"] == 100.0

    standard_metrics_resp = client.get("/api/metrics", params={"site_id": site_id})
    assert standard_metrics_resp.status_code == 200
    standard_metrics = {row["metric"]: row for row in standard_metrics_resp.json()["metrics"]}
    assert standard_metrics["pageviews"]["value"] == 100.0
    assert standard_metrics["conversions"]["value"] == 25.0
    assert standard_metrics["conversion_rate"]["value"] == 0.25


@pytest.mark.asyncio
async def test_missing_site_plan_defaults_to_free_for_serving(client):
    site_id = "site-default-plan-free"
    base_start = datetime(2026, 4, 11, 14, 0, tzinfo=timezone.utc)

    # No site_plan row for this site on purpose: serving should fall back to free.
    await _insert_dp_window(
        site_id=site_id,
        plan="free",
        metric="pageviews",
        value=7.0,
        window_start=base_start,
    )
    await _insert_dp_window(
        site_id=site_id,
        plan="standard",
        metric="pageviews",
        value=70.0,
        window_start=base_start,
    )

    aggregate_resp = client.get(
        "/api/aggregate",
        params={"site_id": site_id, "metric": "pageviews", "window": "standard"},
    )
    assert aggregate_resp.status_code == 200
    windows = aggregate_resp.json()["windows"]
    assert windows
    assert windows[0]["value"] == 7.0

    metrics_resp = client.get("/api/metrics", params={"site_id": site_id})
    assert metrics_resp.status_code == 200
    metrics_map = {row["metric"]: row for row in metrics_resp.json()["metrics"]}
    assert metrics_map["pageviews"]["value"] == 7.0


@pytest.mark.asyncio
async def test_metrics_sums_windows_within_selected_range(client):
    site_id = "site-metrics-sum"
    start = datetime(2026, 4, 18, 12, 0, tzinfo=timezone.utc)
    await _set_site_plan(site_id, "free")
    await _insert_dp_window(site_id=site_id, plan="free", metric="pageviews", value=3.0, window_start=start)
    await _insert_dp_window(
        site_id=site_id,
        plan="free",
        metric="pageviews",
        value=4.0,
        window_start=start + timedelta(minutes=15),
    )
    await _insert_dp_window(site_id=site_id, plan="free", metric="conversions", value=1.0, window_start=start)
    await _insert_dp_window(
        site_id=site_id,
        plan="free",
        metric="conversions",
        value=2.0,
        window_start=start + timedelta(minutes=15),
    )

    metrics_resp = client.get("/api/metrics", params={"site_id": site_id})
    assert metrics_resp.status_code == 200
    metrics_map = {row["metric"]: row for row in metrics_resp.json()["metrics"]}
    assert metrics_map["pageviews"]["value"] == 7.0
    assert metrics_map["conversions"]["value"] == 3.0
    assert metrics_map["conversion_rate"]["value"] == pytest.approx(3.0 / 7.0, rel=1e-6)


@pytest.mark.asyncio
async def test_metrics_surface_fresh_forecast_anomaly_flags(client):
    site_id = "site-metric-anomaly-flags"
    now = datetime.now(timezone.utc)
    window_start = now.replace(second=0, microsecond=0) - timedelta(minutes=30)
    await _set_site_plan(site_id, "free")
    for metric in ("pageviews", "revenue", "uniques"):
        await _insert_dp_window(site_id=site_id, plan="free", metric=metric, value=25.0, window_start=window_start)

    async with async_session_factory() as session:
        # Fresh + anomalous -> surfaced as True.
        session.add(
            Forecast(
                site_id=site_id, plan="free", metric="pageviews", day=now.date() + timedelta(days=1),
                yhat=10, yhat_lower=8, yhat_upper=12, mape=0.2, has_anomaly=True, z_score=3.1, trained_at=now, model_id=None,
            )
        )
        # Fresh + normal -> False.
        session.add(
            Forecast(
                site_id=site_id, plan="free", metric="revenue", day=now.date() + timedelta(days=1),
                yhat=10, yhat_lower=8, yhat_upper=12, mape=0.2, has_anomaly=False, z_score=0.4, trained_at=now, model_id=None,
            )
        )
        # Stale + anomalous -> must NOT surface (failed freshness gate).
        session.add(
            Forecast(
                site_id=site_id, plan="free", metric="uniques", day=now.date() + timedelta(days=1),
                yhat=10, yhat_lower=8, yhat_upper=12, mape=0.2, has_anomaly=True, z_score=3.1,
                trained_at=now - timedelta(days=5), model_id=None,
            )
        )
        await session.commit()

    resp = client.get("/api/metrics", params={"site_id": site_id})
    assert resp.status_code == 200
    metrics_map = {row["metric"]: row for row in resp.json()["metrics"]}
    assert metrics_map["pageviews"]["has_anomaly"] is True
    assert metrics_map["revenue"]["has_anomaly"] is False
    assert metrics_map["uniques"]["has_anomaly"] is False


@pytest.mark.asyncio
async def test_reducer_uses_revenue_payload_value_for_live_events(client):
    site_id = "site-revenue-live-events"
    base = datetime(2026, 4, 19, 16, 0, tzinfo=timezone.utc)
    await _set_site_plan(site_id, "free")
    await _insert_raw_report(
        site_id=site_id,
        kind="revenue",
        payload={"value": 39.99, "currency": "USD", "conversion_type": "purchase", "order_id": "ord_1"},
        day=base.date(),
        server_received_at=base,
    )
    await _insert_raw_report(
        site_id=site_id,
        kind="revenue",
        payload={"value": 10.01, "currency": "USD", "conversion_type": "purchase", "order_id": "ord_2"},
        day=base.date(),
        server_received_at=base + timedelta(minutes=5),
    )

    original_min_reports = reduce_settings.MIN_REPORTS_PER_WINDOW
    reduce_settings.MIN_REPORTS_PER_WINDOW = 1
    try:
        async with async_session_factory() as session:
            await reduce_reports(session, start_day=base.date(), end_day=base.date())
    finally:
        reduce_settings.MIN_REPORTS_PER_WINDOW = original_min_reports

    aggregate_resp = client.get(
        "/api/aggregate",
        params={"site_id": site_id, "metric": "revenue", "window": "standard"},
    )
    assert aggregate_resp.status_code == 200
    total = sum(row["value"] for row in aggregate_resp.json()["windows"])
    assert total == pytest.approx(50.0, rel=1e-6)


@pytest.mark.asyncio
async def test_hostname_filter_scopes_free_aggregate_and_breakdown(client):
    site_id = "site-hostname-filter"
    day = date(2026, 4, 20)
    await _set_site_plan(site_id, "free")
    original_auth_enabled = dashboard_auth_settings.DASHBOARD_AUTH_ENABLED
    original_allow_unclaimed = dashboard_auth_settings.DASHBOARD_ALLOW_UNCLAIMED_SITES
    dashboard_auth_settings.DASHBOARD_AUTH_ENABLED = False
    dashboard_auth_settings.DASHBOARD_ALLOW_UNCLAIMED_SITES = True

    try:
        await _insert_raw_report(
            site_id=site_id,
            kind="pageviews",
            payload={"url": "/", "_hostname": "neurotypicaltranslator.com"},
            day=day,
            server_received_at=datetime(2026, 4, 20, 9, 0, tzinfo=timezone.utc),
        )
        await _insert_raw_report(
            site_id=site_id,
            kind="pageviews",
            payload={"url": "/app", "_hostname": "app.neurotypicaltranslator.com"},
            day=day,
            server_received_at=datetime(2026, 4, 20, 9, 15, tzinfo=timezone.utc),
        )
        await _insert_raw_report(
            site_id=site_id,
            kind="pageviews",
            payload={"url": "/app/settings", "_hostname": "app.neurotypicaltranslator.com"},
            day=day,
            server_received_at=datetime(2026, 4, 20, 9, 30, tzinfo=timezone.utc),
        )
        await _insert_raw_report(
            site_id=site_id,
            kind="sessions",
            payload={
                "_hostname": "app.neurotypicaltranslator.com",
                "_session_hmac": "sess-host-a",
                "_visitor_day_hmac": "visitor-host-a",
                "referrer_bucket": "direct",
                "referrer_source": "direct",
            },
            day=day,
            server_received_at=datetime(2026, 4, 20, 9, 15, tzinfo=timezone.utc),
        )
        await _insert_raw_report(
            site_id=site_id,
            kind="sessions",
            payload={
                "_hostname": "app.neurotypicaltranslator.com",
                "_session_hmac": "sess-host-b",
                "_visitor_day_hmac": "visitor-host-b",
                "referrer_bucket": "organic",
                "referrer_source": "google.com",
            },
            day=day,
            server_received_at=datetime(2026, 4, 20, 9, 45, tzinfo=timezone.utc),
        )
        await _insert_raw_report(
            site_id=site_id,
            kind="sessions",
            payload={
                "_hostname": "app.neurotypicaltranslator.com",
                "_session_hmac": "sess-host-c",
                "_visitor_day_hmac": "visitor-host-c",
                "referrer_bucket": "direct",
                "referrer_source": "direct",
            },
            day=day,
            server_received_at=datetime(2026, 4, 20, 10, 0, tzinfo=timezone.utc),
        )
        await _insert_raw_report(
            site_id=site_id,
            kind="sessions",
            payload={
                "_hostname": "app.neurotypicaltranslator.com",
                "_session_hmac": "sess-host-d",
                "_visitor_day_hmac": "visitor-host-d",
                "referrer_bucket": "organic",
                "referrer_source": "google.com",
            },
            day=day,
            server_received_at=datetime(2026, 4, 20, 10, 15, tzinfo=timezone.utc),
        )
        await _insert_raw_report(
            site_id=site_id,
            kind="uniques",
            payload={
                "_hostname": "app.neurotypicaltranslator.com",
                "_visitor_day_hmac": "visitor-host-a",
            },
            day=day,
            server_received_at=datetime(2026, 4, 20, 9, 16, tzinfo=timezone.utc),
        )
        await _insert_raw_report(
            site_id=site_id,
            kind="uniques",
            payload={
                "_hostname": "app.neurotypicaltranslator.com",
                "_visitor_day_hmac": "visitor-host-a",
            },
            day=day,
            server_received_at=datetime(2026, 4, 20, 9, 46, tzinfo=timezone.utc),
        )
        await _insert_raw_report(
            site_id=site_id,
            kind="uniques",
            payload={
                "_hostname": "app.neurotypicaltranslator.com",
                "_visitor_day_hmac": "visitor-host-b",
            },
            day=day,
            server_received_at=datetime(2026, 4, 20, 10, 1, tzinfo=timezone.utc),
        )

        original_min_reports = aggregate_settings.MIN_REPORTS_PER_WINDOW
        aggregate_settings.MIN_REPORTS_PER_WINDOW = 1
        try:
            agg_resp = client.get(
                "/api/aggregate",
                params={
                    "site_id": site_id,
                    "metric": "pageviews",
                    "window": "standard",
                    "hostname": "app.neurotypicaltranslator.com",
                },
            )
            assert agg_resp.status_code == 200
            agg_total = sum(row["value"] for row in agg_resp.json()["windows"])
            assert agg_total == 2.0

            uniques_resp = client.get(
                "/api/aggregate",
                params={
                    "site_id": site_id,
                    "metric": "uniques",
                    "window": "standard",
                    "hostname": "app.neurotypicaltranslator.com",
                },
            )
            assert uniques_resp.status_code == 200
            uniques_total = sum(row["value"] for row in uniques_resp.json()["windows"])
            # Deduped by visitor-day marker, so duplicate unique reports collapse.
            assert uniques_total == 2.0
        finally:
            aggregate_settings.MIN_REPORTS_PER_WINDOW = original_min_reports

        hosts_resp = client.get(
            "/api/breakdown",
            params={
                "site_id": site_id,
                "dimension": "hostnames",
                "start": "2026-04-20",
                "end": "2026-04-20",
                "limit": 10,
            },
        )
        assert hosts_resp.status_code == 200
        host_rows = hosts_resp.json()["rows"]
        assert host_rows[0]["label"] == "app.neurotypicaltranslator.com"
        assert host_rows[0]["metrics"]["sessions"] == 4.0

        filtered_sources = client.get(
            "/api/breakdown",
            params={
                "site_id": site_id,
                "dimension": "sources",
                "hostname": "app.neurotypicaltranslator.com",
                "start": "2026-04-20",
                "end": "2026-04-20",
                "limit": 10,
            },
        )
        assert filtered_sources.status_code == 200
        source_rows = filtered_sources.json()["rows"]
        labels = {row["label"] for row in source_rows}
        assert labels == {"Direct", "Google"}
    finally:
        dashboard_auth_settings.DASHBOARD_AUTH_ENABLED = original_auth_enabled
        dashboard_auth_settings.DASHBOARD_ALLOW_UNCLAIMED_SITES = original_allow_unclaimed


@pytest.mark.asyncio
async def test_breakdown_endpoint_returns_real_dimension_rows(client):
    site_id = "site-breakdown-live"
    target_day = date(2026, 4, 11)
    await _set_site_plan(site_id, "standard")

    pageview_payloads = [
        (
            {
                "url": "/",
                "_device_bucket": "mobile",
                "_country_code": "US",
                "_session_hmac": "sess-a",
                "_visitor_day_hmac": "visitor-a",
            },
            datetime(2026, 4, 11, 9, 1, tzinfo=timezone.utc),
        ),
        (
            {
                "url": "/",
                "_device_bucket": "desktop",
                "_country_code": "US",
                "_session_hmac": "sess-b",
                "_visitor_day_hmac": "visitor-b",
            },
            datetime(2026, 4, 11, 9, 6, tzinfo=timezone.utc),
        ),
        (
            {
                "url": "/pricing",
                "_device_bucket": "desktop",
                "_country_code": "CA",
                "_session_hmac": "sess-c",
                "_visitor_day_hmac": "visitor-c",
            },
            datetime(2026, 4, 11, 9, 36, tzinfo=timezone.utc),
        ),
        (
            {
                "url": "https://neurotypicaltranslator.com/blog/post-1?utm_source=test",
                "_device_bucket": "mobile",
                "_country_code": "US",
                "_session_hmac": "sess-a",
                "_visitor_day_hmac": "visitor-a",
            },
            datetime(2026, 4, 11, 9, 20, tzinfo=timezone.utc),
        ),
        (
            {
                "url": "/should-ignore",
                "_device_bucket": "mobile",
                "_country_code": "US",
                "_session_hmac": "sess-z",
                "_visitor_day_hmac": "visitor-z",
                "historical_import": True,
            },
            datetime(2026, 4, 11, 9, 45, tzinfo=timezone.utc),
        ),
    ]
    for payload, received_at in pageview_payloads:
        await _insert_raw_report(
            site_id=site_id,
            kind="pageviews",
            payload=payload,
            day=target_day,
            server_received_at=received_at,
        )

    session_payloads = [
        (
            {
                "referrer_bucket": "organic",
                "referrer_source": "google.com",
                "_session_hmac": "sess-a",
                "_visitor_day_hmac": "visitor-a",
                "_device_bucket": "mobile",
                "_country_code": "US",
            },
            datetime(2026, 4, 11, 9, 0, tzinfo=timezone.utc),
        ),
        (
            {
                "referrer_bucket": "external",
                "_session_hmac": "sess-a",
                "_visitor_day_hmac": "visitor-a",
                "_device_bucket": "mobile",
                "_country_code": "US",
            },
            datetime(2026, 4, 11, 9, 5, tzinfo=timezone.utc),
        ),
        (
            {
                "referrer_bucket": "direct",
                "_session_hmac": "sess-b",
                "_visitor_day_hmac": "visitor-b",
                "_device_bucket": "desktop",
                "_country_code": "US",
            },
            datetime(2026, 4, 11, 9, 6, tzinfo=timezone.utc),
        ),
        (
            {
                "referrer_bucket": "organic",
                "referrer_source": "google.com",
                "_session_hmac": "sess-c",
                "_visitor_day_hmac": "visitor-c",
                "_device_bucket": "desktop",
                "_country_code": "CA",
            },
            datetime(2026, 4, 11, 9, 35, tzinfo=timezone.utc),
        ),
    ]
    for payload, received_at in session_payloads:
        await _insert_raw_report(
            site_id=site_id,
            kind="sessions",
            payload=payload,
            day=target_day,
            server_received_at=received_at,
        )

    conversion_payloads = [
        (
            {
                "conversion_type": "demo_request",
                "_session_hmac": "sess-a",
                "_visitor_day_hmac": "visitor-a",
                "_device_bucket": "mobile",
                "_country_code": "US",
            },
            datetime(2026, 4, 11, 9, 2, tzinfo=timezone.utc),
        ),
        (
            {
                "conversion_type": "demo_request",
                "_session_hmac": "sess-c",
                "_visitor_day_hmac": "visitor-c",
                "_device_bucket": "desktop",
                "_country_code": "CA",
            },
            datetime(2026, 4, 11, 9, 38, tzinfo=timezone.utc),
        ),
        (
            {
                "conversion_type": "contact_us",
                "_session_hmac": "sess-b",
                "_visitor_day_hmac": "visitor-b",
                "_device_bucket": "desktop",
                "_country_code": "US",
            },
            datetime(2026, 4, 11, 9, 7, tzinfo=timezone.utc),
        ),
        (
            {
                "conversion_type": "",
                "_session_hmac": "sess-z",
                "_visitor_day_hmac": "visitor-z",
                "historical_import": True,
            },
            datetime(2026, 4, 11, 9, 50, tzinfo=timezone.utc),
        ),
    ]
    for payload, received_at in conversion_payloads:
        await _insert_raw_report(
            site_id=site_id,
            kind="conversions",
            payload=payload,
            day=target_day,
            server_received_at=received_at,
        )

    query = {"site_id": site_id, "start": target_day.isoformat(), "end": target_day.isoformat(), "limit": 10}

    pages_resp = client.get("/api/breakdown", params={**query, "dimension": "pages"})
    assert pages_resp.status_code == 200
    pages_body = pages_resp.json()
    assert pages_body["total"] == 2.0
    assert pages_body["primary_metric"] == "pageviews"
    assert pages_body["metric_keys"] == ["uniques", "sessions", "pageviews"]
    assert pages_body["rows"] == [
        {"label": "/", "value": 2.0, "metrics": {"uniques": 2.0, "sessions": 2.0, "pageviews": 2.0}},
    ]

    sources_resp = client.get("/api/breakdown", params={**query, "dimension": "sources"})
    assert sources_resp.status_code == 200
    assert sources_resp.json()["primary_metric"] == "sessions"
    assert sources_resp.json()["rows"] == [
        {
            "label": "Google",
            "value": 2.0,
            "metrics": {"uniques": 2.0, "sessions": 2.0, "pageviews": 3.0, "conversions": 2.0},
        },
    ]

    devices_resp = client.get("/api/breakdown", params={**query, "dimension": "devices"})
    assert devices_resp.status_code == 200
    assert devices_resp.json()["rows"] == [
        {
            "label": "Desktop",
            "value": 2.0,
            "metrics": {"uniques": 2.0, "sessions": 2.0, "pageviews": 2.0, "conversions": 2.0},
        },
        {
            "label": "Mobile",
            "value": 2.0,
            "metrics": {"uniques": 1.0, "sessions": 1.0, "pageviews": 2.0, "conversions": 1.0},
        },
    ]

    countries_resp = client.get("/api/breakdown", params={**query, "dimension": "countries"})
    assert countries_resp.status_code == 200
    assert countries_resp.json()["rows"] == [
        {
            "label": "US",
            "value": 3.0,
            "metrics": {"uniques": 2.0, "sessions": 2.0, "pageviews": 3.0, "conversions": 2.0},
        },
        {
            "label": "CA",
            "value": 1.0,
            "metrics": {"uniques": 1.0, "sessions": 1.0, "pageviews": 1.0, "conversions": 1.0},
        },
    ]

    hour_resp = client.get("/api/breakdown", params={**query, "dimension": "hour_of_day"})
    assert hour_resp.status_code == 200
    assert hour_resp.json()["rows"] == []
    assert hour_resp.json()["total"] == 0.0

    weekday_resp = client.get("/api/breakdown", params={**query, "dimension": "day_of_week"})
    assert weekday_resp.status_code == 200
    assert weekday_resp.json()["rows"] == []
    assert weekday_resp.json()["total"] == 0.0

    conversions_resp = client.get("/api/breakdown", params={**query, "dimension": "conversions"})
    assert conversions_resp.status_code == 200
    assert conversions_resp.json()["rows"] == [
        {
            "label": "Demo Request",
            "value": 2.0,
            "metrics": {"uniques": 2.0, "sessions": 2.0, "conversions": 2.0},
        },
    ]


@pytest.mark.asyncio
async def test_time_parting_breakdown_requires_min_range_and_k_threshold(client):
    site_id = "site-time-parting-private"
    await _set_site_plan(site_id, "standard")

    start_day = date(2026, 4, 5)
    end_day = date(2026, 4, 11)
    for offset in range(7):
        day = start_day + timedelta(days=offset)
        for session_index in range(2):
            timestamp = datetime(2026, 4, 5 + offset, 9, 5 + session_index, tzinfo=timezone.utc)
            await _insert_raw_report(
                site_id=site_id,
                kind="sessions",
                payload={
                    "referrer_bucket": "direct",
                    "_session_hmac": f"sess-{offset}-{session_index}",
                    "_visitor_day_hmac": f"visitor-{offset}-{session_index}",
                },
                day=day,
                server_received_at=timestamp,
            )

    short_range_resp = client.get(
        "/api/breakdown",
        params={"site_id": site_id, "dimension": "hour_of_day", "start": "2026-04-11", "end": "2026-04-11"},
    )
    assert short_range_resp.status_code == 200
    assert short_range_resp.json()["rows"] == []

    full_range_resp = client.get(
        "/api/breakdown",
        params={"site_id": site_id, "dimension": "hour_of_day", "start": start_day.isoformat(), "end": end_day.isoformat()},
    )
    assert full_range_resp.status_code == 200
    assert full_range_resp.json()["rows"] == [
        {
            "label": "9 AM",
            "value": 14.0,
            "metrics": {"uniques": 14.0, "sessions": 14.0, "pageviews": 0.0, "conversions": 0.0},
        }
    ]
    assert full_range_resp.json()["total"] == 14.0

    weekday_resp = client.get(
        "/api/breakdown",
        params={"site_id": site_id, "dimension": "day_of_week", "start": start_day.isoformat(), "end": end_day.isoformat()},
    )
    assert weekday_resp.status_code == 200
    assert weekday_resp.json()["rows"] == []

    for index in range(8):
        await _insert_raw_report(
            site_id=site_id,
            kind="sessions",
            payload={
                "referrer_bucket": "direct",
                "_session_hmac": f"sess-sat-{index}",
                "_visitor_day_hmac": f"visitor-sat-{index}",
            },
            day=end_day,
            server_received_at=datetime(2026, 4, 11, 10, 10 + index, tzinfo=timezone.utc),
        )

    weekday_after_boost_resp = client.get(
        "/api/breakdown",
        params={"site_id": site_id, "dimension": "day_of_week", "start": start_day.isoformat(), "end": end_day.isoformat()},
    )
    assert weekday_after_boost_resp.status_code == 200
    assert weekday_after_boost_resp.json()["rows"] == [
        {
            "label": "Saturday",
            "value": 10.0,
            "metrics": {"uniques": 10.0, "sessions": 10.0, "pageviews": 0.0, "conversions": 0.0},
        }
    ]


@pytest.mark.asyncio
async def test_time_parting_hour_of_day_can_filter_weekdays_and_weekends(client):
    site_id = "site-time-parting-day-type"
    await _set_site_plan(site_id, "standard")
    start_day = date(2026, 4, 5)
    end_day = date(2026, 4, 11)
    for index in range(10):
        await _insert_raw_report(
            site_id=site_id,
            kind="sessions",
            payload={
                "referrer_bucket": "direct",
                "_session_hmac": f"weekday-{index}",
                "_visitor_day_hmac": f"weekday-visitor-{index}",
            },
            day=date(2026, 4, 6),
            server_received_at=datetime(2026, 4, 6, 9, index, tzinfo=timezone.utc),
        )
        await _insert_raw_report(
            site_id=site_id,
            kind="sessions",
            payload={
                "referrer_bucket": "direct",
                "_session_hmac": f"weekend-{index}",
                "_visitor_day_hmac": f"weekend-visitor-{index}",
            },
            day=end_day,
            server_received_at=datetime(2026, 4, 11, 11, index, tzinfo=timezone.utc),
        )

    base_params = {
        "site_id": site_id,
        "dimension": "hour_of_day",
        "start": start_day.isoformat(),
        "end": end_day.isoformat(),
    }
    weekday_resp = client.get("/api/breakdown", params={**base_params, "day_type": "weekday"})
    assert weekday_resp.status_code == 200
    assert weekday_resp.json()["rows"] == [
        {
            "label": "9 AM",
            "value": 10.0,
            "metrics": {"uniques": 10.0, "sessions": 10.0, "pageviews": 0.0, "conversions": 0.0},
        }
    ]

    weekend_resp = client.get("/api/breakdown", params={**base_params, "day_type": "weekend"})
    assert weekend_resp.status_code == 200
    assert weekend_resp.json()["rows"] == [
        {
            "label": "11 AM",
            "value": 10.0,
            "metrics": {"uniques": 10.0, "sessions": 10.0, "pageviews": 0.0, "conversions": 0.0},
        }
    ]

    local_site_id = "site-time-parting-local-day-type"
    await _set_site_plan(local_site_id, "standard")
    for index in range(10):
        await _insert_raw_report(
            site_id=local_site_id,
            kind="sessions",
            payload={
                "referrer_bucket": "direct",
                "_timezone_hint": "America/Chicago",
                "_session_hmac": f"local-weekday-{index}",
                "_visitor_day_hmac": f"local-weekday-visitor-{index}",
            },
            day=date(2026, 4, 10),
            server_received_at=datetime(2026, 4, 11, 1, index, tzinfo=timezone.utc),
        )

    local_params = {**base_params, "site_id": local_site_id}
    local_weekday_resp = client.get("/api/breakdown", params={**local_params, "day_type": "weekday"})
    assert local_weekday_resp.status_code == 200
    assert local_weekday_resp.json()["rows"] == [
        {
            "label": "8 PM",
            "value": 10.0,
            "metrics": {"uniques": 10.0, "sessions": 10.0, "pageviews": 0.0, "conversions": 0.0},
        }
    ]

    local_weekend_resp = client.get("/api/breakdown", params={**local_params, "day_type": "weekend"})
    assert local_weekend_resp.status_code == 200
    assert local_weekend_resp.json()["rows"] == []


@pytest.mark.asyncio
async def test_dashboard_auth_can_gate_metrics_endpoints(client):
    site_id = "site-dashboard-auth-gate"
    base_start = datetime(2026, 4, 11, 16, 0, tzinfo=timezone.utc)
    await _set_site_plan(site_id, "free")
    await _insert_dp_window(
        site_id=site_id,
        plan="free",
        metric="pageviews",
        value=9.0,
        window_start=base_start,
    )

    original = (
        dashboard_auth_settings.DASHBOARD_AUTH_ENABLED,
        dashboard_auth_settings.DASHBOARD_AUTH_USERNAME,
        dashboard_auth_settings.DASHBOARD_AUTH_PASSWORD,
        dashboard_auth_settings.DASHBOARD_AUTH_USERS_JSON,
        dashboard_auth_settings.DASHBOARD_AUTH_SECRET,
        dashboard_auth_settings.DASHBOARD_AUTH_TTL_SECONDS,
        dashboard_auth_settings.DASHBOARD_ALLOWED_SITE_IDS,
        dashboard_auth_settings.DASHBOARD_SITE_ACCESS_JSON,
        dashboard_auth_settings.DASHBOARD_ALLOW_UNCLAIMED_SITES,
    )
    dashboard_auth_settings.DASHBOARD_AUTH_ENABLED = True
    dashboard_auth_settings.DASHBOARD_AUTH_USERNAME = "owner"
    dashboard_auth_settings.DASHBOARD_AUTH_PASSWORD = "secret-pass"
    dashboard_auth_settings.DASHBOARD_AUTH_USERS_JSON = None
    dashboard_auth_settings.DASHBOARD_AUTH_SECRET = "dashboard-auth-test-secret"
    dashboard_auth_settings.DASHBOARD_AUTH_TTL_SECONDS = 3600
    dashboard_auth_settings.DASHBOARD_ALLOWED_SITE_IDS = site_id
    dashboard_auth_settings.DASHBOARD_SITE_ACCESS_JSON = None
    dashboard_auth_settings.DASHBOARD_ALLOW_UNCLAIMED_SITES = False
    dashboard_auth_module._parse_auth_users.cache_clear()
    dashboard_auth_module._parse_site_access_map.cache_clear()
    try:
        status_resp = client.get("/api/auth/status")
        assert status_resp.status_code == 200
        assert status_resp.json()["enabled"] is True

        unauthorized_metrics = client.get("/api/metrics", params={"site_id": site_id})
        assert unauthorized_metrics.status_code == 401
        unauthorized_breakdown = client.get(
            "/api/breakdown",
            params={"site_id": site_id, "dimension": "pages"},
        )
        assert unauthorized_breakdown.status_code == 401
        unauthorized_jobs = client.get("/api/jobs/status")
        assert unauthorized_jobs.status_code == 401
        unauthorized_checkout = client.post(
            "/api/checkout/session",
            json={"site_id": site_id, "plan": "standard"},
        )
        assert unauthorized_checkout.status_code == 401
        unauthorized_billing = client.get("/api/billing/status", params={"site_id": site_id})
        assert unauthorized_billing.status_code == 401

        bad_login = client.post("/api/auth/login", json={"username": "owner", "password": "wrong"})
        assert bad_login.status_code == 401

        good_login = client.post("/api/auth/login", json={"username": "owner", "password": "secret-pass"})
        assert good_login.status_code == 200
        set_cookie_header = good_login.headers.get("set-cookie", "").lower()
        assert dashboard_auth_settings.DASHBOARD_AUTH_COOKIE_NAME in set_cookie_header
        assert "httponly" in set_cookie_header
        access_token = good_login.json()["access_token"]
        assert access_token

        me_cookie_resp = client.get("/api/auth/me")
        assert me_cookie_resp.status_code == 200
        assert me_cookie_resp.json()["username"] == "owner"

        me_resp = client.get("/api/auth/me", headers={"Authorization": f"Bearer {access_token}"})
        assert me_resp.status_code == 200
        assert me_resp.json()["username"] == "owner"

        cookie_authorized_metrics = client.get(
            "/api/metrics",
            params={"site_id": site_id},
        )
        assert cookie_authorized_metrics.status_code == 200

        authorized_metrics = client.get(
            "/api/metrics",
            params={"site_id": site_id},
            headers={"Authorization": f"Bearer {access_token}"},
        )
        assert authorized_metrics.status_code == 200
        authorized_breakdown = client.get(
            "/api/breakdown",
            params={"site_id": site_id, "dimension": "pages"},
            headers={"Authorization": f"Bearer {access_token}"},
        )
        assert authorized_breakdown.status_code == 200
        authorized_jobs = client.get("/api/jobs/status", headers={"Authorization": f"Bearer {access_token}"})
        assert authorized_jobs.status_code == 200
        authorized_checkout = client.post(
            "/api/checkout/session",
            json={"site_id": site_id, "plan": "standard"},
            headers={"Authorization": f"Bearer {access_token}"},
        )
        assert authorized_checkout.status_code in {502, 503}
        authorized_billing = client.get(
            "/api/billing/status",
            params={"site_id": site_id},
            headers={"Authorization": f"Bearer {access_token}"},
        )
        assert authorized_billing.status_code == 200
        billing_body = authorized_billing.json()
        assert billing_body["site_id"] == site_id
        assert billing_body["plan"] == "free"

        forbidden_metrics = client.get(
            "/api/metrics",
            params={"site_id": "site-not-owned"},
            headers={"Authorization": f"Bearer {access_token}"},
        )
        assert forbidden_metrics.status_code == 403

        dashboard_auth_settings.DASHBOARD_ALLOWED_SITE_IDS = None
        dashboard_auth_settings.DASHBOARD_SITE_ACCESS_JSON = '{"someone-else":["site-not-owned"]}'
        dashboard_auth_module._parse_site_access_map.cache_clear()
        unmapped_owner = client.get(
            "/api/metrics",
            params={"site_id": site_id},
            headers={"Authorization": f"Bearer {access_token}"},
        )
        assert unmapped_owner.status_code == 403

        dashboard_auth_settings.DASHBOARD_SITE_ACCESS_JSON = f'{{"owner":["{site_id}"]}}'
        dashboard_auth_module._parse_site_access_map.cache_clear()
        mapped_owner = client.get(
            "/api/metrics",
            params={"site_id": site_id},
            headers={"Authorization": f"Bearer {access_token}"},
        )
        assert mapped_owner.status_code == 200

        logout = client.post("/api/auth/logout")
        assert logout.status_code == 200
        assert "max-age=0" in logout.headers.get("set-cookie", "").lower()
        logged_out_me = client.get("/api/auth/me")
        assert logged_out_me.status_code == 401
        bearer_after_logout = client.get("/api/auth/me", headers={"Authorization": f"Bearer {access_token}"})
        assert bearer_after_logout.status_code == 200
    finally:
        dashboard_auth_module._parse_auth_users.cache_clear()
        dashboard_auth_module._parse_site_access_map.cache_clear()
        (
            dashboard_auth_settings.DASHBOARD_AUTH_ENABLED,
            dashboard_auth_settings.DASHBOARD_AUTH_USERNAME,
            dashboard_auth_settings.DASHBOARD_AUTH_PASSWORD,
            dashboard_auth_settings.DASHBOARD_AUTH_USERS_JSON,
            dashboard_auth_settings.DASHBOARD_AUTH_SECRET,
            dashboard_auth_settings.DASHBOARD_AUTH_TTL_SECONDS,
            dashboard_auth_settings.DASHBOARD_ALLOWED_SITE_IDS,
            dashboard_auth_settings.DASHBOARD_SITE_ACCESS_JSON,
            dashboard_auth_settings.DASHBOARD_ALLOW_UNCLAIMED_SITES,
        ) = original


@pytest.mark.asyncio
async def test_dashboard_auth_multi_user_site_isolation(client):
    site_alice = "site-alice-private"
    site_bob = "site-bob-private"
    base_start = datetime(2026, 4, 11, 17, 0, tzinfo=timezone.utc)
    await _set_site_plan(site_alice, "free")
    await _set_site_plan(site_bob, "free")
    await _insert_dp_window(
        site_id=site_alice,
        plan="free",
        metric="pageviews",
        value=11.0,
        window_start=base_start,
    )
    await _insert_dp_window(
        site_id=site_bob,
        plan="free",
        metric="pageviews",
        value=7.0,
        window_start=base_start,
    )

    original = (
        dashboard_auth_settings.DASHBOARD_AUTH_ENABLED,
        dashboard_auth_settings.DASHBOARD_AUTH_USERNAME,
        dashboard_auth_settings.DASHBOARD_AUTH_PASSWORD,
        dashboard_auth_settings.DASHBOARD_AUTH_USERS_JSON,
        dashboard_auth_settings.DASHBOARD_AUTH_SECRET,
        dashboard_auth_settings.DASHBOARD_AUTH_TTL_SECONDS,
        dashboard_auth_settings.DASHBOARD_ALLOWED_SITE_IDS,
        dashboard_auth_settings.DASHBOARD_SITE_ACCESS_JSON,
        dashboard_auth_settings.DASHBOARD_ALLOW_UNCLAIMED_SITES,
    )
    dashboard_auth_settings.DASHBOARD_AUTH_ENABLED = True
    dashboard_auth_settings.DASHBOARD_AUTH_USERNAME = "admin"
    dashboard_auth_settings.DASHBOARD_AUTH_PASSWORD = None
    dashboard_auth_settings.DASHBOARD_AUTH_USERS_JSON = '{"alice":"pw-alice","bob":"pw-bob"}'
    dashboard_auth_settings.DASHBOARD_AUTH_SECRET = "dashboard-auth-multi-user-secret"
    dashboard_auth_settings.DASHBOARD_AUTH_TTL_SECONDS = 3600
    dashboard_auth_settings.DASHBOARD_ALLOWED_SITE_IDS = None
    dashboard_auth_settings.DASHBOARD_SITE_ACCESS_JSON = (
        f'{{"alice":["{site_alice}"],"bob":["{site_bob}"]}}'
    )
    dashboard_auth_settings.DASHBOARD_ALLOW_UNCLAIMED_SITES = False
    dashboard_auth_module._parse_auth_users.cache_clear()
    dashboard_auth_module._parse_site_access_map.cache_clear()
    try:
        alice_login = client.post("/api/auth/login", json={"username": "alice", "password": "pw-alice"})
        assert alice_login.status_code == 200
        alice_token = alice_login.json()["access_token"]

        bob_login = client.post("/api/auth/login", json={"username": "bob", "password": "pw-bob"})
        assert bob_login.status_code == 200
        bob_token = bob_login.json()["access_token"]

        wrong_password = client.post("/api/auth/login", json={"username": "alice", "password": "wrong"})
        assert wrong_password.status_code == 401

        alice_own = client.get(
            "/api/metrics",
            params={"site_id": site_alice},
            headers={"Authorization": f"Bearer {alice_token}"},
        )
        assert alice_own.status_code == 200
        alice_other = client.get(
            "/api/metrics",
            params={"site_id": site_bob},
            headers={"Authorization": f"Bearer {alice_token}"},
        )
        assert alice_other.status_code == 403

        bob_own = client.get(
            "/api/metrics",
            params={"site_id": site_bob},
            headers={"Authorization": f"Bearer {bob_token}"},
        )
        assert bob_own.status_code == 200
        bob_other = client.get(
            "/api/metrics",
            params={"site_id": site_alice},
            headers={"Authorization": f"Bearer {bob_token}"},
        )
        assert bob_other.status_code == 403
    finally:
        dashboard_auth_module._parse_auth_users.cache_clear()
        dashboard_auth_module._parse_site_access_map.cache_clear()
        (
            dashboard_auth_settings.DASHBOARD_AUTH_ENABLED,
            dashboard_auth_settings.DASHBOARD_AUTH_USERNAME,
            dashboard_auth_settings.DASHBOARD_AUTH_PASSWORD,
            dashboard_auth_settings.DASHBOARD_AUTH_USERS_JSON,
            dashboard_auth_settings.DASHBOARD_AUTH_SECRET,
            dashboard_auth_settings.DASHBOARD_AUTH_TTL_SECONDS,
            dashboard_auth_settings.DASHBOARD_ALLOWED_SITE_IDS,
            dashboard_auth_settings.DASHBOARD_SITE_ACCESS_JSON,
            dashboard_auth_settings.DASHBOARD_ALLOW_UNCLAIMED_SITES,
        ) = original


@pytest.mark.asyncio
async def test_dashboard_auth_site_access_map_missing_user_falls_back_to_db_owner(client):
    site_id = "site-db-owner-fallback"
    owner = "owner-fallback"
    base_start = datetime(2026, 4, 11, 18, 0, tzinfo=timezone.utc)
    await _set_site_plan(site_id, "free")
    await _insert_dp_window(
        site_id=site_id,
        plan="free",
        metric="pageviews",
        value=6.0,
        window_start=base_start,
    )
    async with async_session_factory() as session:
        session.add(
            DashboardUser(
                username=owner,
                email=f"{owner}@example.com",
                password_hash=PasswordHasher().hash("pw-owner-fallback"),
            )
        )
        session.add(
            DashboardSite(
                site_id=site_id,
                owner_username=owner,
                site_name="Owner Fallback Site",
                allowed_origin="https://owner-fallback.example.com",
            )
        )
        await session.commit()

    original = (
        dashboard_auth_settings.DASHBOARD_AUTH_ENABLED,
        dashboard_auth_settings.DASHBOARD_AUTH_USERNAME,
        dashboard_auth_settings.DASHBOARD_AUTH_PASSWORD,
        dashboard_auth_settings.DASHBOARD_AUTH_USERS_JSON,
        dashboard_auth_settings.DASHBOARD_AUTH_SECRET,
        dashboard_auth_settings.DASHBOARD_AUTH_TTL_SECONDS,
        dashboard_auth_settings.DASHBOARD_ALLOWED_SITE_IDS,
        dashboard_auth_settings.DASHBOARD_SITE_ACCESS_JSON,
        dashboard_auth_settings.DASHBOARD_ALLOW_UNCLAIMED_SITES,
    )
    dashboard_auth_settings.DASHBOARD_AUTH_ENABLED = True
    dashboard_auth_settings.DASHBOARD_AUTH_USERNAME = "admin"
    dashboard_auth_settings.DASHBOARD_AUTH_PASSWORD = None
    dashboard_auth_settings.DASHBOARD_AUTH_USERS_JSON = f'{{"{owner}":"pw-owner-fallback"}}'
    dashboard_auth_settings.DASHBOARD_AUTH_SECRET = "dashboard-auth-owner-fallback-secret"
    dashboard_auth_settings.DASHBOARD_AUTH_TTL_SECONDS = 3600
    dashboard_auth_settings.DASHBOARD_ALLOWED_SITE_IDS = None
    dashboard_auth_settings.DASHBOARD_SITE_ACCESS_JSON = '{"someone-else":["another-site"]}'
    dashboard_auth_settings.DASHBOARD_ALLOW_UNCLAIMED_SITES = False
    dashboard_auth_module._parse_auth_users.cache_clear()
    dashboard_auth_module._parse_site_access_map.cache_clear()
    try:
        login = client.post("/api/auth/login", json={"username": owner, "password": "pw-owner-fallback"})
        assert login.status_code == 200
        token = login.json()["access_token"]
        resp = client.get(
            "/api/metrics",
            params={"site_id": site_id},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 200
    finally:
        dashboard_auth_module._parse_auth_users.cache_clear()
        dashboard_auth_module._parse_site_access_map.cache_clear()
        (
            dashboard_auth_settings.DASHBOARD_AUTH_ENABLED,
            dashboard_auth_settings.DASHBOARD_AUTH_USERNAME,
            dashboard_auth_settings.DASHBOARD_AUTH_PASSWORD,
            dashboard_auth_settings.DASHBOARD_AUTH_USERS_JSON,
            dashboard_auth_settings.DASHBOARD_AUTH_SECRET,
            dashboard_auth_settings.DASHBOARD_AUTH_TTL_SECONDS,
            dashboard_auth_settings.DASHBOARD_ALLOWED_SITE_IDS,
            dashboard_auth_settings.DASHBOARD_SITE_ACCESS_JSON,
            dashboard_auth_settings.DASHBOARD_ALLOW_UNCLAIMED_SITES,
        ) = original


@pytest.mark.asyncio
async def test_dashboard_auth_site_access_map_overrides_global_allowed_site_ids(client):
    site_id = "site-access-map-overrides-allowlist"
    base_start = datetime(2026, 4, 11, 18, 30, tzinfo=timezone.utc)
    await _set_site_plan(site_id, "free")
    await _insert_dp_window(
        site_id=site_id,
        plan="free",
        metric="pageviews",
        value=5.0,
        window_start=base_start,
    )

    original = (
        dashboard_auth_settings.DASHBOARD_AUTH_ENABLED,
        dashboard_auth_settings.DASHBOARD_AUTH_USERNAME,
        dashboard_auth_settings.DASHBOARD_AUTH_PASSWORD,
        dashboard_auth_settings.DASHBOARD_AUTH_USERS_JSON,
        dashboard_auth_settings.DASHBOARD_AUTH_SECRET,
        dashboard_auth_settings.DASHBOARD_AUTH_TTL_SECONDS,
        dashboard_auth_settings.DASHBOARD_ALLOWED_SITE_IDS,
        dashboard_auth_settings.DASHBOARD_SITE_ACCESS_JSON,
        dashboard_auth_settings.DASHBOARD_ALLOW_UNCLAIMED_SITES,
    )
    dashboard_auth_settings.DASHBOARD_AUTH_ENABLED = True
    dashboard_auth_settings.DASHBOARD_AUTH_USERNAME = "admin"
    dashboard_auth_settings.DASHBOARD_AUTH_PASSWORD = None
    dashboard_auth_settings.DASHBOARD_AUTH_USERS_JSON = '{"validheather":"pw-heather"}'
    dashboard_auth_settings.DASHBOARD_AUTH_SECRET = "dashboard-auth-map-precedence-secret"
    dashboard_auth_settings.DASHBOARD_AUTH_TTL_SECONDS = 3600
    dashboard_auth_settings.DASHBOARD_ALLOWED_SITE_IDS = "live-validanalytics-io"
    dashboard_auth_settings.DASHBOARD_SITE_ACCESS_JSON = (
        '{"validheather":["site-access-map-overrides-allowlist"]}'
    )
    dashboard_auth_settings.DASHBOARD_ALLOW_UNCLAIMED_SITES = False
    dashboard_auth_module._parse_auth_users.cache_clear()
    dashboard_auth_module._parse_site_access_map.cache_clear()
    try:
        login = client.post("/api/auth/login", json={"username": "validheather", "password": "pw-heather"})
        assert login.status_code == 200
        token = login.json()["access_token"]

        resp = client.get(
            "/api/metrics",
            params={"site_id": site_id},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 200
    finally:
        dashboard_auth_module._parse_auth_users.cache_clear()
        dashboard_auth_module._parse_site_access_map.cache_clear()
        (
            dashboard_auth_settings.DASHBOARD_AUTH_ENABLED,
            dashboard_auth_settings.DASHBOARD_AUTH_USERNAME,
            dashboard_auth_settings.DASHBOARD_AUTH_PASSWORD,
            dashboard_auth_settings.DASHBOARD_AUTH_USERS_JSON,
            dashboard_auth_settings.DASHBOARD_AUTH_SECRET,
            dashboard_auth_settings.DASHBOARD_AUTH_TTL_SECONDS,
            dashboard_auth_settings.DASHBOARD_ALLOWED_SITE_IDS,
            dashboard_auth_settings.DASHBOARD_SITE_ACCESS_JSON,
            dashboard_auth_settings.DASHBOARD_ALLOW_UNCLAIMED_SITES,
        ) = original


@pytest.mark.asyncio
async def test_dashboard_auth_unclaimed_sites_require_explicit_opt_in(client):
    site_id = "site-unclaimed-access"
    base_start = datetime(2026, 4, 11, 17, 0, tzinfo=timezone.utc)
    await _set_site_plan(site_id, "free")
    await _insert_dp_window(
        site_id=site_id,
        plan="free",
        metric="pageviews",
        value=3.0,
        window_start=base_start,
    )

    original = (
        dashboard_auth_settings.DASHBOARD_AUTH_ENABLED,
        dashboard_auth_settings.DASHBOARD_AUTH_USERNAME,
        dashboard_auth_settings.DASHBOARD_AUTH_PASSWORD,
        dashboard_auth_settings.DASHBOARD_AUTH_USERS_JSON,
        dashboard_auth_settings.DASHBOARD_AUTH_SECRET,
        dashboard_auth_settings.DASHBOARD_AUTH_TTL_SECONDS,
        dashboard_auth_settings.DASHBOARD_ALLOWED_SITE_IDS,
        dashboard_auth_settings.DASHBOARD_SITE_ACCESS_JSON,
        dashboard_auth_settings.DASHBOARD_ALLOW_UNCLAIMED_SITES,
    )
    dashboard_auth_settings.DASHBOARD_AUTH_ENABLED = True
    dashboard_auth_settings.DASHBOARD_AUTH_USERNAME = "admin"
    dashboard_auth_settings.DASHBOARD_AUTH_PASSWORD = None
    dashboard_auth_settings.DASHBOARD_AUTH_USERS_JSON = '{"alice":"pw-alice"}'
    dashboard_auth_settings.DASHBOARD_AUTH_SECRET = "dashboard-auth-unclaimed-site-secret"
    dashboard_auth_settings.DASHBOARD_AUTH_TTL_SECONDS = 3600
    dashboard_auth_settings.DASHBOARD_ALLOWED_SITE_IDS = None
    dashboard_auth_settings.DASHBOARD_SITE_ACCESS_JSON = None
    dashboard_auth_settings.DASHBOARD_ALLOW_UNCLAIMED_SITES = False
    dashboard_auth_module._parse_auth_users.cache_clear()
    dashboard_auth_module._parse_site_access_map.cache_clear()
    try:
        login = client.post("/api/auth/login", json={"username": "alice", "password": "pw-alice"})
        assert login.status_code == 200
        token = login.json()["access_token"]

        blocked = client.get(
            "/api/metrics",
            params={"site_id": site_id},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert blocked.status_code == 403

        dashboard_auth_settings.DASHBOARD_ALLOW_UNCLAIMED_SITES = True
        allowed = client.get(
            "/api/metrics",
            params={"site_id": site_id},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert allowed.status_code == 200
    finally:
        dashboard_auth_module._parse_auth_users.cache_clear()
        dashboard_auth_module._parse_site_access_map.cache_clear()
        (
            dashboard_auth_settings.DASHBOARD_AUTH_ENABLED,
            dashboard_auth_settings.DASHBOARD_AUTH_USERNAME,
            dashboard_auth_settings.DASHBOARD_AUTH_PASSWORD,
            dashboard_auth_settings.DASHBOARD_AUTH_USERS_JSON,
            dashboard_auth_settings.DASHBOARD_AUTH_SECRET,
            dashboard_auth_settings.DASHBOARD_AUTH_TTL_SECONDS,
            dashboard_auth_settings.DASHBOARD_ALLOWED_SITE_IDS,
            dashboard_auth_settings.DASHBOARD_SITE_ACCESS_JSON,
            dashboard_auth_settings.DASHBOARD_ALLOW_UNCLAIMED_SITES,
        ) = original


@pytest.mark.asyncio
async def test_site_settings_update_claims_unclaimed_site_for_authed_user(client):
    site_id = "site-settings-unclaimed"
    await _set_site_plan(site_id, "free")

    original = (
        dashboard_auth_settings.DASHBOARD_AUTH_ENABLED,
        dashboard_auth_settings.DASHBOARD_AUTH_USERNAME,
        dashboard_auth_settings.DASHBOARD_AUTH_PASSWORD,
        dashboard_auth_settings.DASHBOARD_AUTH_USERS_JSON,
        dashboard_auth_settings.DASHBOARD_AUTH_SECRET,
        dashboard_auth_settings.DASHBOARD_AUTH_TTL_SECONDS,
        dashboard_auth_settings.DASHBOARD_ALLOWED_SITE_IDS,
        dashboard_auth_settings.DASHBOARD_SITE_ACCESS_JSON,
        dashboard_auth_settings.DASHBOARD_ALLOW_UNCLAIMED_SITES,
    )
    dashboard_auth_settings.DASHBOARD_AUTH_ENABLED = True
    dashboard_auth_settings.DASHBOARD_AUTH_USERNAME = "admin"
    dashboard_auth_settings.DASHBOARD_AUTH_PASSWORD = None
    dashboard_auth_settings.DASHBOARD_AUTH_USERS_JSON = '{"alice":"pw-alice"}'
    dashboard_auth_settings.DASHBOARD_AUTH_SECRET = "dashboard-auth-site-settings-secret"
    dashboard_auth_settings.DASHBOARD_AUTH_TTL_SECONDS = 3600
    dashboard_auth_settings.DASHBOARD_ALLOWED_SITE_IDS = None
    dashboard_auth_settings.DASHBOARD_SITE_ACCESS_JSON = None
    dashboard_auth_settings.DASHBOARD_ALLOW_UNCLAIMED_SITES = True
    dashboard_auth_module._parse_auth_users.cache_clear()
    dashboard_auth_module._parse_site_access_map.cache_clear()
    try:
        login = client.post("/api/auth/login", json={"username": "alice", "password": "pw-alice"})
        assert login.status_code == 200
        token = login.json()["access_token"]
        headers = {"Authorization": f"Bearer {token}"}

        update = client.put(
            "/api/site-settings",
            params={"site_id": site_id},
            json={"timezone": "America/Chicago"},
            headers=headers,
        )
        assert update.status_code == 200, update.text
        assert update.json()["timezone"] == "America/Chicago"

        fetched = client.get("/api/site-settings", params={"site_id": site_id}, headers=headers)
        assert fetched.status_code == 200
        assert fetched.json()["timezone"] == "America/Chicago"

        async with async_session_factory() as session:
            row = await session.get(DashboardSite, site_id)
            assert row is not None
            assert row.owner_username == "alice"
            assert row.timezone == "America/Chicago"
    finally:
        dashboard_auth_module._parse_auth_users.cache_clear()
        dashboard_auth_module._parse_site_access_map.cache_clear()
        (
            dashboard_auth_settings.DASHBOARD_AUTH_ENABLED,
            dashboard_auth_settings.DASHBOARD_AUTH_USERNAME,
            dashboard_auth_settings.DASHBOARD_AUTH_PASSWORD,
            dashboard_auth_settings.DASHBOARD_AUTH_USERS_JSON,
            dashboard_auth_settings.DASHBOARD_AUTH_SECRET,
            dashboard_auth_settings.DASHBOARD_AUTH_TTL_SECONDS,
            dashboard_auth_settings.DASHBOARD_ALLOWED_SITE_IDS,
            dashboard_auth_settings.DASHBOARD_SITE_ACCESS_JSON,
            dashboard_auth_settings.DASHBOARD_ALLOW_UNCLAIMED_SITES,
        ) = original


@pytest.mark.asyncio
async def test_public_signup_free_creates_user_site_and_key(client):
    original = (
        dashboard_auth_settings.DASHBOARD_AUTH_ENABLED,
        dashboard_auth_settings.DASHBOARD_AUTH_USERNAME,
        dashboard_auth_settings.DASHBOARD_AUTH_PASSWORD,
        dashboard_auth_settings.DASHBOARD_AUTH_USERS_JSON,
        dashboard_auth_settings.DASHBOARD_AUTH_SECRET,
        dashboard_auth_settings.DASHBOARD_AUTH_TTL_SECONDS,
        dashboard_auth_settings.DASHBOARD_ALLOWED_SITE_IDS,
        dashboard_auth_settings.DASHBOARD_SITE_ACCESS_JSON,
    )
    dashboard_auth_settings.DASHBOARD_AUTH_ENABLED = True
    dashboard_auth_settings.DASHBOARD_AUTH_USERNAME = "admin"
    dashboard_auth_settings.DASHBOARD_AUTH_PASSWORD = None
    dashboard_auth_settings.DASHBOARD_AUTH_USERS_JSON = None
    dashboard_auth_settings.DASHBOARD_AUTH_SECRET = "dashboard-auth-public-signup-secret"
    dashboard_auth_settings.DASHBOARD_AUTH_TTL_SECONDS = 3600
    dashboard_auth_settings.DASHBOARD_ALLOWED_SITE_IDS = None
    dashboard_auth_settings.DASHBOARD_SITE_ACCESS_JSON = None
    dashboard_auth_module._parse_auth_users.cache_clear()
    dashboard_auth_module._parse_site_access_map.cache_clear()
    try:
        signup = client.post(
            "/api/public/signup",
            json={
                "username": "signup_free_user",
                "email": "signup-free@example.com",
                "password": "strong-pass-123",
                "site_name": "Signup Free Site",
                "site_domain": "example-signup-free.com",
                "plan": "free",
            },
        )
        assert signup.status_code == 201
        body = signup.json()
        assert body["requires_checkout"] is False
        assert body["checkout_url"] is None
        assert body["site_id"].startswith("live-example-signup-free-com")
        assert body["site_key"].startswith("vsk_")
        assert body["access_token"]

        async with async_session_factory() as session:
            user = await session.get(DashboardUser, "signup_free_user")
            assert user is not None
            assert user.password_hash != "strong-pass-123"
            site = await session.get(DashboardSite, body["site_id"])
            assert site is not None
            assert site.owner_username == "signup_free_user"
            plan = await session.get(SitePlan, body["site_id"])
            assert plan is not None
            assert plan.plan == "free"

        login = client.post("/api/auth/login", json={"username": "signup_free_user", "password": "strong-pass-123"})
        assert login.status_code == 200
        token = login.json()["access_token"]
        assert token

        sites = client.get("/api/sites", headers={"Authorization": f"Bearer {token}"})
        assert sites.status_code == 200
        assert sites.json()["sites"] == [
            {
                "site_id": body["site_id"],
                "site_name": "Signup Free Site",
                "allowed_origin": "https://example-signup-free.com",
                "plan": "free",
            }
        ]

        own_metrics = client.get("/api/metrics", params={"site_id": body["site_id"]}, headers={"Authorization": f"Bearer {token}"})
        assert own_metrics.status_code == 200
    finally:
        dashboard_auth_module._parse_auth_users.cache_clear()
        dashboard_auth_module._parse_site_access_map.cache_clear()
        (
            dashboard_auth_settings.DASHBOARD_AUTH_ENABLED,
            dashboard_auth_settings.DASHBOARD_AUTH_USERNAME,
            dashboard_auth_settings.DASHBOARD_AUTH_PASSWORD,
            dashboard_auth_settings.DASHBOARD_AUTH_USERS_JSON,
            dashboard_auth_settings.DASHBOARD_AUTH_SECRET,
            dashboard_auth_settings.DASHBOARD_AUTH_TTL_SECONDS,
            dashboard_auth_settings.DASHBOARD_ALLOWED_SITE_IDS,
            dashboard_auth_settings.DASHBOARD_SITE_ACCESS_JSON,
        ) = original


@pytest.mark.asyncio
async def test_public_signup_standard_returns_checkout_url(client, monkeypatch):
    from app.routers import public_signup as public_signup_router

    original_auth = (
        dashboard_auth_settings.DASHBOARD_AUTH_ENABLED,
        dashboard_auth_settings.DASHBOARD_AUTH_USERNAME,
        dashboard_auth_settings.DASHBOARD_AUTH_PASSWORD,
        dashboard_auth_settings.DASHBOARD_AUTH_USERS_JSON,
        dashboard_auth_settings.DASHBOARD_AUTH_SECRET,
        dashboard_auth_settings.DASHBOARD_AUTH_TTL_SECONDS,
        dashboard_auth_settings.DASHBOARD_ALLOWED_SITE_IDS,
        dashboard_auth_settings.DASHBOARD_SITE_ACCESS_JSON,
    )
    original_stripe = (
        public_signup_router.settings.STRIPE_SECRET_KEY,
        public_signup_router.settings.STRIPE_STANDARD_PRICE_ID,
        public_signup_router.settings.STRIPE_SIGNUP_SUCCESS_URL,
        public_signup_router.settings.STRIPE_SIGNUP_CANCEL_URL,
    )
    dashboard_auth_settings.DASHBOARD_AUTH_ENABLED = True
    dashboard_auth_settings.DASHBOARD_AUTH_USERNAME = "admin"
    dashboard_auth_settings.DASHBOARD_AUTH_PASSWORD = None
    dashboard_auth_settings.DASHBOARD_AUTH_USERS_JSON = None
    dashboard_auth_settings.DASHBOARD_AUTH_SECRET = "dashboard-auth-public-signup-standard-secret"
    dashboard_auth_settings.DASHBOARD_AUTH_TTL_SECONDS = 3600
    dashboard_auth_settings.DASHBOARD_ALLOWED_SITE_IDS = None
    dashboard_auth_settings.DASHBOARD_SITE_ACCESS_JSON = None
    public_signup_router.settings.STRIPE_SECRET_KEY = "sk_test_mock"
    public_signup_router.settings.STRIPE_STANDARD_PRICE_ID = "price_mock_standard"
    public_signup_router.settings.STRIPE_SIGNUP_SUCCESS_URL = "https://validanalytics.io/signup/complete"
    public_signup_router.settings.STRIPE_SIGNUP_CANCEL_URL = "https://validanalytics.io/signup"
    dashboard_auth_module._parse_auth_users.cache_clear()
    dashboard_auth_module._parse_site_access_map.cache_clear()

    class _FakeSession:
        url = "https://checkout.stripe.test/session_123"

    def _fake_checkout_create(**_kwargs):
        return _FakeSession()

    monkeypatch.setattr(public_signup_router.stripe.checkout.Session, "create", _fake_checkout_create)

    try:
        signup = client.post(
            "/api/public/signup",
            json={
                "username": "signup_standard_user",
                "email": "signup-standard@example.com",
                "password": "strong-pass-456",
                "site_name": "Signup Standard Site",
                "site_domain": "example-signup-standard.com",
                "plan": "standard",
            },
        )
        assert signup.status_code == 201
        body = signup.json()
        assert body["requires_checkout"] is True
        assert body["checkout_url"] == "https://checkout.stripe.test/session_123"
        assert body["site_key"].startswith("vsk_")

        async with async_session_factory() as session:
            plan = await session.get(SitePlan, body["site_id"])
            assert plan is not None
            # Standard activates after Stripe webhook completes.
            assert plan.plan == "free"
    finally:
        dashboard_auth_module._parse_auth_users.cache_clear()
        dashboard_auth_module._parse_site_access_map.cache_clear()
        (
            dashboard_auth_settings.DASHBOARD_AUTH_ENABLED,
            dashboard_auth_settings.DASHBOARD_AUTH_USERNAME,
            dashboard_auth_settings.DASHBOARD_AUTH_PASSWORD,
            dashboard_auth_settings.DASHBOARD_AUTH_USERS_JSON,
            dashboard_auth_settings.DASHBOARD_AUTH_SECRET,
            dashboard_auth_settings.DASHBOARD_AUTH_TTL_SECONDS,
            dashboard_auth_settings.DASHBOARD_ALLOWED_SITE_IDS,
            dashboard_auth_settings.DASHBOARD_SITE_ACCESS_JSON,
        ) = original_auth
        (
            public_signup_router.settings.STRIPE_SECRET_KEY,
            public_signup_router.settings.STRIPE_STANDARD_PRICE_ID,
            public_signup_router.settings.STRIPE_SIGNUP_SUCCESS_URL,
            public_signup_router.settings.STRIPE_SIGNUP_CANCEL_URL,
        ) = original_stripe


def test_collect_token_dependency_rejects_admin_token_fallback():
    from fastapi import HTTPException

    from app.access_control import require_collect_endpoint_token

    # The admin token must no longer be accepted as a fallback on the collect endpoint.
    with pytest.raises(HTTPException) as exc:
        require_collect_endpoint_token(x_collect_token=os.environ["ADMIN_API_TOKEN"])
    assert exc.value.status_code == 401

    # The dedicated collect token still works.
    require_collect_endpoint_token(x_collect_token=os.environ["COLLECT_ENDPOINT_TOKEN"])


def test_alert_webhook_requires_token(client):
    payload = {"source": "reducer", "severity": "warning", "message": "stale reducer", "metadata": {}}

    missing = client.post("/api/alert/webhook", json=payload)
    assert missing.status_code == 401

    wrong = client.post("/api/alert/webhook", json=payload, headers={"X-Alert-Token": "not-the-token"})
    assert wrong.status_code == 401


def test_alert_webhook_accepts_valid_token(client, monkeypatch):
    import app.routers.alert_webhook as alert_webhook_module

    forwarded: list = []

    async def _fake_forward(payload):
        forwarded.append(payload)

    monkeypatch.setattr(alert_webhook_module, "forward_to_sidecar", _fake_forward)

    payload = {"source": "reducer", "severity": "critical", "message": "no events", "metadata": {"site_id": "x"}}
    resp = client.post(
        "/api/alert/webhook",
        json=payload,
        headers={"X-Alert-Token": os.environ["ALERT_WEBHOOK_TOKEN"]},
    )
    assert resp.status_code == 202
    assert len(forwarded) == 1


def test_login_is_rate_limited(client):
    import app.routers.auth as auth_router

    original = (
        dashboard_auth_settings.DASHBOARD_AUTH_ENABLED,
        dashboard_auth_settings.DASHBOARD_AUTH_USERNAME,
        dashboard_auth_settings.DASHBOARD_AUTH_PASSWORD,
        dashboard_auth_settings.DASHBOARD_AUTH_USERS_JSON,
        dashboard_auth_settings.DASHBOARD_AUTH_SECRET,
        dashboard_auth_settings.LOGIN_RATE_LIMIT_PER_MINUTE,
    )
    dashboard_auth_settings.DASHBOARD_AUTH_ENABLED = True
    dashboard_auth_settings.DASHBOARD_AUTH_USERNAME = "rl-owner"
    dashboard_auth_settings.DASHBOARD_AUTH_PASSWORD = "rl-pass"
    dashboard_auth_settings.DASHBOARD_AUTH_USERS_JSON = None
    dashboard_auth_settings.DASHBOARD_AUTH_SECRET = "login-rate-limit-secret"
    dashboard_auth_settings.LOGIN_RATE_LIMIT_PER_MINUTE = 3
    dashboard_auth_module._parse_auth_users.cache_clear()
    auth_router.login_rate_limiter.clear()
    try:
        statuses = [
            client.post("/api/auth/login", json={"username": "rl-owner", "password": "wrong"}).status_code
            for _ in range(4)
        ]
        # First 3 attempts are processed (and rejected for bad credentials),
        # the 4th trips the per-IP limiter.
        assert statuses[:3] == [401, 401, 401]
        assert statuses[3] == 429
    finally:
        dashboard_auth_module._parse_auth_users.cache_clear()
        auth_router.login_rate_limiter.clear()
        (
            dashboard_auth_settings.DASHBOARD_AUTH_ENABLED,
            dashboard_auth_settings.DASHBOARD_AUTH_USERNAME,
            dashboard_auth_settings.DASHBOARD_AUTH_PASSWORD,
            dashboard_auth_settings.DASHBOARD_AUTH_USERS_JSON,
            dashboard_auth_settings.DASHBOARD_AUTH_SECRET,
            dashboard_auth_settings.LOGIN_RATE_LIMIT_PER_MINUTE,
        ) = original


@pytest.mark.asyncio
async def test_checkout_rejects_disallowed_redirect_url(client, monkeypatch):
    import app.routers.stripe_billing as stripe_billing

    site_id = "site-redirect-allowlist"
    await _set_site_plan(site_id, "free")

    original_auth = (
        dashboard_auth_settings.DASHBOARD_AUTH_ENABLED,
        dashboard_auth_settings.DASHBOARD_AUTH_USERNAME,
        dashboard_auth_settings.DASHBOARD_AUTH_PASSWORD,
        dashboard_auth_settings.DASHBOARD_AUTH_USERS_JSON,
        dashboard_auth_settings.DASHBOARD_AUTH_SECRET,
        dashboard_auth_settings.DASHBOARD_ALLOWED_SITE_IDS,
        dashboard_auth_settings.DASHBOARD_SITE_ACCESS_JSON,
    )
    original_stripe = (
        stripe_billing.settings.STRIPE_SECRET_KEY,
        stripe_billing.settings.STRIPE_WEBHOOK_SECRET,
        stripe_billing.settings.STRIPE_STANDARD_PRICE_ID,
    )
    dashboard_auth_settings.DASHBOARD_AUTH_ENABLED = True
    dashboard_auth_settings.DASHBOARD_AUTH_USERNAME = "redir-owner"
    dashboard_auth_settings.DASHBOARD_AUTH_PASSWORD = "redir-pass"
    dashboard_auth_settings.DASHBOARD_AUTH_USERS_JSON = None
    dashboard_auth_settings.DASHBOARD_AUTH_SECRET = "redirect-allowlist-secret"
    dashboard_auth_settings.DASHBOARD_ALLOWED_SITE_IDS = site_id
    dashboard_auth_settings.DASHBOARD_SITE_ACCESS_JSON = None
    stripe_billing.settings.STRIPE_SECRET_KEY = "sk_test_mock"
    stripe_billing.settings.STRIPE_WEBHOOK_SECRET = "whsec_mock"
    stripe_billing.settings.STRIPE_STANDARD_PRICE_ID = "price_mock_standard"
    dashboard_auth_module._parse_auth_users.cache_clear()
    dashboard_auth_module._parse_site_access_map.cache_clear()
    stripe_billing._allowed_redirect_origins.cache_clear()

    created: dict = {}

    def _fake_checkout_create(**kwargs):
        created.update(kwargs)
        return SimpleNamespace(url="https://stripe.test/session", id="cs_test_123")

    monkeypatch.setattr(stripe_billing.stripe.checkout.Session, "create", _fake_checkout_create)
    try:
        login = client.post("/api/auth/login", json={"username": "redir-owner", "password": "redir-pass"})
        assert login.status_code == 200
        headers = {"Authorization": f"Bearer {login.json()['access_token']}"}

        bad = client.post(
            "/api/checkout/session",
            json={"site_id": site_id, "plan": "standard", "success_url": "https://evil.example.com/win"},
            headers=headers,
        )
        assert bad.status_code == 400

        good = client.post(
            "/api/checkout/session",
            json={
                "site_id": site_id,
                "plan": "standard",
                "success_url": "https://app.validanalytics.io/billing/success",
            },
            headers=headers,
        )
        assert good.status_code == 200
        assert created["success_url"].startswith("https://app.validanalytics.io/billing/success")
    finally:
        dashboard_auth_module._parse_auth_users.cache_clear()
        dashboard_auth_module._parse_site_access_map.cache_clear()
        stripe_billing._allowed_redirect_origins.cache_clear()
        (
            dashboard_auth_settings.DASHBOARD_AUTH_ENABLED,
            dashboard_auth_settings.DASHBOARD_AUTH_USERNAME,
            dashboard_auth_settings.DASHBOARD_AUTH_PASSWORD,
            dashboard_auth_settings.DASHBOARD_AUTH_USERS_JSON,
            dashboard_auth_settings.DASHBOARD_AUTH_SECRET,
            dashboard_auth_settings.DASHBOARD_ALLOWED_SITE_IDS,
            dashboard_auth_settings.DASHBOARD_SITE_ACCESS_JSON,
        ) = original_auth
        (
            stripe_billing.settings.STRIPE_SECRET_KEY,
            stripe_billing.settings.STRIPE_WEBHOOK_SECRET,
            stripe_billing.settings.STRIPE_STANDARD_PRICE_ID,
        ) = original_stripe
