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
os.environ["UPLOAD_TOKEN_SECRET"] = "test-upload-token-secret"
os.environ["SESSION_HMAC_SECRET"] = "test-session-hmac-secret"
os.environ["ADMIN_API_TOKEN"] = "test-admin-api-token"
os.environ["COLLECT_ENDPOINT_TOKEN"] = "test-collect-token"

ADMIN_HEADERS = {"X-Admin-Token": os.environ["ADMIN_API_TOKEN"]}
COLLECT_HEADERS = {"X-Collect-Token": os.environ["COLLECT_ENDPOINT_TOKEN"]}

from app.main import app  # noqa: E402
from sqlalchemy import select

from argon2 import PasswordHasher

from app.models import Base, DashboardSite, DashboardUser, DpWindow, IS_POSTGRES, LdpReport, RawReport, SiteApiKey, SitePlan, async_engine, async_session_factory  # noqa: E402
from app.dashboard_auth import settings as dashboard_auth_settings  # noqa: E402
from app import dashboard_auth as dashboard_auth_module  # noqa: E402
from app.routers.aggregates import settings as aggregate_settings  # noqa: E402
from app.routers.shuffle import derive_daily_visitor_key, derive_standard_session_key  # noqa: E402
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
        headers={"Origin": "https://example.com", "X-Bypass-Delay": "true"},
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
        headers=ADMIN_HEADERS,
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
        authorized_jobs = client.get("/api/jobs/status", headers={"Authorization": f"Bearer {access_token}"})
        assert authorized_jobs.status_code == 200
        authorized_checkout = client.post(
            "/api/checkout/session",
            json={"site_id": site_id, "plan": "standard"},
            headers={"Authorization": f"Bearer {access_token}"},
        )
        assert authorized_checkout.status_code in {502, 503}

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
