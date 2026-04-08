import asyncio
import os
import sys
from datetime import datetime, timedelta, timezone
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
    now_iso = datetime.now(timezone.utc).isoformat()
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
            await reduce_reports(session, days=1)
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
