import asyncio
import os
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

# Add the parent directory to Python path so we can import the app module
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

TEST_DB_PATH = Path(__file__).parent / "test.db"
os.environ["DATABASE_URL"] = f"sqlite+aiosqlite:///{TEST_DB_PATH}"
os.environ["SESSION_HMAC_SECRET"] = "test-session-hmac-secret"

from app.main import app  # noqa: E402
from sqlalchemy import select

from argon2 import PasswordHasher

from app.models import Base, DpWindow, IS_POSTGRES, LdpReport, RawReport, SiteApiKey, SitePlan, async_engine, async_session_factory  # noqa: E402
from app.dashboard_auth import settings as dashboard_auth_settings  # noqa: E402
from app.routers.shuffle import derive_standard_session_key  # noqa: E402
from app.scheduler.nightly_reduce import reduce_reports, settings as reduce_settings  # noqa: E402


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
    )
    assert response.status_code == 200
    token = response.json()["token"]
    jti = response.json()["jti"]

    revoke = client.post("/api/admin/revoke-token", json={"jti": jti})
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
async def test_nonce_replay_rejected(client):
    token_resp = client.post(
        "/api/upload-token",
        json={
            "site_id": "site-a",
            "allowed_origin": "https://example.com",
            "epsilon_budget": 1.0,
            "sampling_rate": 1.0,
        },
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
        headers={"Origin": "https://example.com", "X-Bypass-Delay": "true"},
    )
    assert first.status_code == 202
    second = client.post(
        "/api/shuffle",
        json={"token": token, "nonce": "same-nonce", "batch": batch},
        headers={"Origin": "https://example.com", "X-Bypass-Delay": "true"},
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
        headers={"X-Bypass-Delay": "true"},
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
        headers={"Origin": "https://example.com", "X-Bypass-Delay": "true"},
    )
    assert resp.status_code == 202  # accepted but dropped internally


@pytest.mark.asyncio
async def test_forecast_requires_history(client):
    response = client.get("/api/forecast/pageviews", params={"site_id": "missing"})
    assert response.status_code == 204


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
            headers={"Origin": "https://example.com", "X-Bypass-Delay": "true"},
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
async def test_scheduler_smoke(client):
    async with async_session_factory() as session:
        await reduce_reports(session, days=1)


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
        headers={"Origin": "https://example.com", "X-Bypass-Delay": "true"},
    )
    assert first.status_code == 202

    replay = client.post(
        "/api/shuffle",
        json={"token": token, "nonce": "session-dedupe-nonce", "batch": batch},
        headers={"Origin": "https://example.com", "X-Bypass-Delay": "true"},
    )
    assert replay.status_code in (401, 409)

    async with async_session_factory() as session:
        original_min_reports = reduce_settings.MIN_REPORTS_PER_WINDOW
        reduce_settings.MIN_REPORTS_PER_WINDOW = 1
        try:
            await reduce_reports(session, start_day=payload_day, end_day=payload_day)
        finally:
            reduce_settings.MIN_REPORTS_PER_WINDOW = original_min_reports
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
async def test_historical_import_requires_token_and_uses_row_value(client):
    await _set_site_plan("site-import", "free")
    old_day = (datetime.now(timezone.utc) - timedelta(days=180)).date().isoformat()

    unauthorized = client.post(
        "/api/import/historical",
        json={"site_id": "site-import", "rows": [{"day": old_day, "metric": "revenue", "value": 42}]},
    )
    assert unauthorized.status_code == 401

    token_resp = client.post(
        "/api/upload-token",
        json={
            "site_id": "site-import",
            "allowed_origin": "https://example.com",
            "epsilon_budget": 1.0,
            "sampling_rate": 1.0,
            "plan": "free",
        },
    )
    token = token_resp.json()["token"]

    imported = client.post(
        "/api/import/historical",
        json={"site_id": "site-import", "rows": [{"day": old_day, "metric": "revenue", "value": 42}]},
        headers={"X-Upload-Token": token},
    )
    assert imported.status_code == 200
    assert imported.json()["imported_rows"] == 1

    async with async_session_factory() as session:
        rows = (
            await session.execute(
                select(DpWindow).where(
                    DpWindow.site_id == "site-import",
                    DpWindow.plan == "free",
                    DpWindow.metric == "revenue",
                )
            )
        ).scalars().all()
        assert rows, "Expected at least one reduced window for imported historical data"
        assert any(abs(row.value - 42.0) < 1e-6 for row in rows)


@pytest.mark.asyncio
async def test_sdk_bootstrap_success_and_origin_failure(client):
    await _set_site_plan("site-bootstrap", "standard")
    site_key = "vsk_bootstrapid_secretvalue"
    await _create_site_api_key("site-bootstrap", "bootstrapid", site_key, "https://example.com")

    denied = client.post(
        "/api/sdk/bootstrap",
        json={"site_key": site_key},
        headers={"Origin": "https://evil.example.com"},
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
async def test_breakdown_endpoint_returns_real_dimension_rows(client):
    site_id = "site-breakdown-live"
    target_day = date(2026, 4, 11)
    await _set_site_plan(site_id, "standard")

    pageview_payloads = [
        {"url": "/", "_device_bucket": "mobile", "_country_code": "US"},
        {"url": "/", "_device_bucket": "desktop", "_country_code": "US"},
        {"url": "/pricing", "_device_bucket": "desktop", "_country_code": "CA"},
        {"url": "https://neurotypicaltranslator.com/blog/post-1?utm_source=test", "_device_bucket": "mobile", "_country_code": "US"},
        {"url": "/should-ignore", "_device_bucket": "mobile", "_country_code": "US", "historical_import": True},
    ]
    for payload in pageview_payloads:
        await _insert_raw_report(site_id=site_id, kind="pageviews", payload=payload, day=target_day)

    session_payloads = [
        {"referrer_bucket": "direct"},
        {"referrer_bucket": "external"},
        {"referrer_bucket": "external"},
    ]
    for payload in session_payloads:
        await _insert_raw_report(site_id=site_id, kind="sessions", payload=payload, day=target_day)

    query = {"site_id": site_id, "start": target_day.isoformat(), "end": target_day.isoformat(), "limit": 10}

    pages_resp = client.get("/api/breakdown", params={**query, "dimension": "pages"})
    assert pages_resp.status_code == 200
    pages_body = pages_resp.json()
    assert pages_body["total"] == 4.0
    assert pages_body["rows"][:3] == [
        {"label": "/", "value": 2.0},
        {"label": "/blog/post-1", "value": 1.0},
        {"label": "/pricing", "value": 1.0},
    ]

    sources_resp = client.get("/api/breakdown", params={**query, "dimension": "sources"})
    assert sources_resp.status_code == 200
    assert sources_resp.json()["rows"] == [
        {"label": "External", "value": 2.0},
        {"label": "Direct", "value": 1.0},
    ]

    devices_resp = client.get("/api/breakdown", params={**query, "dimension": "devices"})
    assert devices_resp.status_code == 200
    assert devices_resp.json()["rows"] == [
        {"label": "Desktop", "value": 2.0},
        {"label": "Mobile", "value": 2.0},
    ]

    countries_resp = client.get("/api/breakdown", params={**query, "dimension": "countries"})
    assert countries_resp.status_code == 200
    assert countries_resp.json()["rows"] == [
        {"label": "US", "value": 3.0},
        {"label": "CA", "value": 1.0},
    ]


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
        dashboard_auth_settings.DASHBOARD_AUTH_SECRET,
        dashboard_auth_settings.DASHBOARD_AUTH_TTL_SECONDS,
    )
    dashboard_auth_settings.DASHBOARD_AUTH_ENABLED = True
    dashboard_auth_settings.DASHBOARD_AUTH_USERNAME = "owner"
    dashboard_auth_settings.DASHBOARD_AUTH_PASSWORD = "secret-pass"
    dashboard_auth_settings.DASHBOARD_AUTH_SECRET = "dashboard-auth-test-secret"
    dashboard_auth_settings.DASHBOARD_AUTH_TTL_SECONDS = 3600
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

        bad_login = client.post("/api/auth/login", json={"username": "owner", "password": "wrong"})
        assert bad_login.status_code == 401

        good_login = client.post("/api/auth/login", json={"username": "owner", "password": "secret-pass"})
        assert good_login.status_code == 200
        access_token = good_login.json()["access_token"]
        assert access_token

        me_resp = client.get("/api/auth/me", headers={"Authorization": f"Bearer {access_token}"})
        assert me_resp.status_code == 200
        assert me_resp.json()["username"] == "owner"

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
    finally:
        (
            dashboard_auth_settings.DASHBOARD_AUTH_ENABLED,
            dashboard_auth_settings.DASHBOARD_AUTH_USERNAME,
            dashboard_auth_settings.DASHBOARD_AUTH_PASSWORD,
            dashboard_auth_settings.DASHBOARD_AUTH_SECRET,
            dashboard_auth_settings.DASHBOARD_AUTH_TTL_SECONDS,
        ) = original
