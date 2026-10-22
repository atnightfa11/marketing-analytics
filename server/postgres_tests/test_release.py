"""Real PostgreSQL checks. Run only through scripts/verify_local_postgres.py."""
import asyncio
import copy
import datetime as dt
import json
import os
from pathlib import Path
import threading
from uuid import uuid4

import pytest

if os.environ.get("VALID_LOCAL_POSTGRES_TEST") != "1":
    pytest.skip("Use the isolated local PostgreSQL runner", allow_module_level=True)

from alembic import command  # noqa: E402
from alembic.config import Config  # noqa: E402
from sqlalchemy import func, select, text  # noqa: E402
from sqlalchemy.ext.asyncio import create_async_engine  # noqa: E402
from sqlalchemy.pool import NullPool  # noqa: E402

from app import models  # noqa: E402


@pytest.fixture(autouse=True)
def no_external_billing(monkeypatch):
    import stripe

    def blocked(*args, **kwargs):
        raise AssertionError("PostgreSQL verification must not contact Stripe")

    monkeypatch.setattr(stripe.http_client.RequestsClient, "request", blocked)


@pytest.fixture(scope="module", autouse=True)
def migrated_database():
    assert models.async_engine.url.database == "valid_release_test"
    assert str(models.async_engine.url.query["host"]).startswith("/tmp/valid-pg-")
    config = Config(str(Path(__file__).parents[1] / "alembic.ini"))
    config.set_main_option("script_location", str(Path(__file__).parents[1] / "alembic"))
    config.set_main_option("prepend_sys_path", str(Path(__file__).parents[1]))
    models.async_engine = create_async_engine(os.environ["DATABASE_URL"], poolclass=NullPool)
    models.async_session_factory.configure(bind=models.async_engine)
    command.upgrade(config, "2026_10_01_capacity_requests")

    async def seed():
        async with models.async_engine.begin() as conn:
            await conn.execute(text("INSERT INTO dashboard_users (username, email, password_hash) "
                                    "VALUES ('existing', 'existing@example.test', 'synthetic')"))
            await conn.execute(text("INSERT INTO dp_windows (site_id, plan, metric, window_start, window_end, "
                                    "value, variance, ci80_low, ci80_high, ci95_low, ci95_high) VALUES "
                                    "('migration-history', 'free', 'pageviews', '2026-10-01', '2026-10-02', "
                                    "123, 0, 123, 123, 123, 123)"))
    asyncio.run(seed())
    command.upgrade(config, "head")
    yield config
    asyncio.run(models.async_engine.dispose())


def test_migration_preserves_users_and_analytics(migrated_database):
    async def check():
        async with models.async_engine.connect() as conn:
            assert await conn.scalar(text("SELECT auth_version FROM dashboard_users WHERE username='existing'")) == 0
            assert await conn.scalar(text("SELECT value FROM dp_windows WHERE site_id='migration-history'")) == 123
            assert await conn.scalar(text("SELECT version_num FROM alembic_version")) == "2026_10_21_account_workflows"
            assert await conn.scalar(text("SELECT to_regclass('password_resets')")) is not None
            assert await conn.scalar(text("SELECT to_regclass('site_provisioning')")) is not None
    asyncio.run(check())


def test_new_migration_roundtrip_and_repeated_upgrade(migrated_database):
    command.downgrade(migrated_database, "2026_10_01_capacity_requests")
    command.upgrade(migrated_database, "head")
    command.upgrade(migrated_database, "head")
    test_migration_preserves_users_and_analytics(migrated_database)


async def seed_owner(prefix, sites=1):
    async with models.async_session_factory() as session:
        session.add(models.DashboardUser(username=prefix, email=f"{prefix}@example.test", password_hash="synthetic"))
        await session.flush()
        for number in range(sites):
            site_id = f"{prefix}-{number}"
            session.add(models.DashboardSite(site_id=site_id, owner_username=prefix,
                                            site_name=site_id, allowed_origin=f"https://{site_id}.test"))
            session.add(models.SitePlan(site_id=site_id, plan="standard" if number == 0 else "free",
                                       stripe_subscription_id=f"sub_{prefix}" if number == 0 else None,
                                       stripe_subscription_status="active" if number == 0 else None))
        await session.commit()


async def post_webhook(event):
    from starlette.requests import Request
    from app.routers.stripe_billing import stripe_webhook

    async def receive():
        return {"type": "http.request", "body": json.dumps(event).encode()}

    request = Request({"type": "http", "headers": [(b"stripe-signature", b"local-stub")]}, receive)
    async with models.async_session_factory() as session:
        return await stripe_webhook(request, session)


@pytest.mark.parametrize("duplicate", [False, True])
def test_webhook_row_lock_and_duplicate_receipt(monkeypatch, duplicate):
    from app.routers import stripe_billing as billing
    monkeypatch.setattr(billing.stripe.Webhook, "construct_event", lambda payload, **_: json.loads(payload))

    async def check():
        prefix = "pg-duplicate" if duplicate else "pg-order"
        await seed_owner(prefix)
        entered, release = asyncio.Event(), asyncio.Event()
        calls = []
        current = {"id": f"sub_{prefix}", "customer": f"cus_{prefix}", "status": "active",
                   "items": {"data": [{"price": {"id": "price_local_standard"}}]}}

        async def retrieve(_):
            snapshot = copy.deepcopy(current)
            calls.append(snapshot)
            if len(calls) == 1:
                entered.set()
                await asyncio.wait_for(release.wait(), 5)
            return snapshot

        monkeypatch.setattr(billing, "_retrieve_current_subscription", retrieve)
        event = {"id": f"evt_{prefix}", "created": 123, "type": "customer.subscription.updated",
                 "data": {"object": {"id": current["id"], "status": "active"}}}
        first = asyncio.create_task(post_webhook(event))
        await asyncio.wait_for(entered.wait(), 5)
        second_event = copy.deepcopy(event)
        if not duplicate:
            second_event["id"] += "_second"
        second = asyncio.create_task(post_webhook(second_event))
        try:
            await asyncio.sleep(0.1)
            assert not second.done()
            assert len(calls) == 1  # No snapshot read before the other transaction commits.
            current["status"] = "canceled"
        finally:
            release.set()
        responses = await asyncio.wait_for(asyncio.gather(first, second), 5)
        assert responses[0]["status"] == "ok"
        assert responses[1]["status"] == ("duplicate" if duplicate else "ok")
        async with models.async_session_factory() as session:
            record = await session.get(models.SitePlan, f"{prefix}-0")
            assert record.stripe_subscription_status == ("active" if duplicate else "canceled")
            assert len(calls) == (1 if duplicate else 2)
    asyncio.run(check())


def test_concurrent_site_creation_cannot_exceed_included_capacity():
    from fastapi import HTTPException
    from app.routers import sites

    async def check():
        await seed_owner("pg-cap", sites=2)

        async def create(number):
            async with models.async_session_factory() as session:
                try:
                    return await sites.create_site(sites.CreateSite(
                        request_id=uuid4(), site_name=f"New {number}", site_domain=f"pg-cap-new-{number}.test",
                    ), {"sub": "pg-cap"}, session)
                except HTTPException as exc:
                    return exc.status_code

        results = await asyncio.gather(create(1), create(2))
        assert sum(isinstance(result, dict) for result in results) == 1
        assert 409 in results
        async with models.async_session_factory() as session:
            count = await session.scalar(select(func.count()).select_from(models.DashboardSite).where(
                models.DashboardSite.owner_username == "pg-cap"))
            assert count == 3
    asyncio.run(check())


def test_concurrent_paid_site_retry_creates_one_site_and_one_slot(monkeypatch):
    from app.routers import sites
    lock = threading.Lock()
    purchases = {}

    def subscription(_):
        with lock:
            return {"status": "active", "items": {"data": list(purchases.values())}}

    def create_item(**kwargs):
        with lock:
            key = kwargs["idempotency_key"]
            if key not in purchases:
                purchases[key] = {"id": "si_pg_extra", "price": {"id": "price_local_extra"},
                                  "quantity": kwargs["quantity"]}
            return purchases[key]

    monkeypatch.setattr(sites.stripe.Subscription, "retrieve", subscription)
    monkeypatch.setattr(sites.stripe.SubscriptionItem, "create", create_item)

    async def check():
        await seed_owner("pg-paid", sites=3)
        payload = sites.CreateSite(request_id=uuid4(), site_name="Fourth", site_domain="pg-paid-fourth.test",
                                   approved_monthly_increase_usd=5)

        async def create():
            async with models.async_session_factory() as session:
                return await sites.create_site(payload, {"sub": "pg-paid"}, session)

        first, second = await asyncio.wait_for(asyncio.gather(create(), create()), 10)
        assert first == second
        assert len(purchases) == 1
        assert next(iter(purchases)) == f"valid-site:{payload.request_id}"
        async with models.async_session_factory() as session:
            count = await session.scalar(select(func.count()).select_from(models.DashboardSite).where(
                models.DashboardSite.owner_username == "pg-paid"))
            assert count == 4
            assert (await session.get(models.SitePlan, "pg-paid-0")).extra_site_quantity == 1
    asyncio.run(check())


@pytest.mark.parametrize("plan", ["free", "standard"])
def test_real_reduction_purge_and_history_after_plan_change(monkeypatch, plan):
    from app.scheduler import nightly_reduce as reducer
    from app.report_history import published_plan_clause
    from app.routers import imports
    from app.schemas import HistoricalImportRow

    monkeypatch.setattr(reducer.settings, "RAW_REPORT_RETENTION_HOURS", 0)
    monkeypatch.setattr(reducer.settings, "FREE_RAW_PURGE_ENABLED", True)

    async def check():
        site_id = f"pg-history-{plan}"
        day = dt.date(2026, 9, 1)
        received = dt.datetime(2026, 9, 1, 14, tzinfo=dt.timezone.utc)
        async with models.async_session_factory() as session:
            session.add(models.SitePlan(site_id=site_id, plan=plan))
            for number in range(3):
                for kind in ("pageviews", "sessions"):
                    session.add(models.RawReport(site_id=site_id, kind=kind, day=day,
                                                 server_received_at=received + dt.timedelta(minutes=number),
                                                 epsilon_used=1, sampling_rate=1, payload={
                        "url": "/test", "referrer_bucket": "direct", "_hostname": "example.test",
                        "_device_bucket": "mobile", "_country_code": "US",
                        "_session_hmac": f"session-{number}", "_visitor_day_hmac": f"visitor-{number}",
                    }))
            await session.commit()
            await reducer.reduce_reports(session, start_day=day, end_day=day, site_id=site_id)
        async with models.async_session_factory() as session:
            watermark = await session.scalar(select(models.ReducerWatermark).where(models.ReducerWatermark.site_id == site_id))
            assert watermark.status == "success" and watermark.raw_purged_at is not None
            assert await session.scalar(select(func.count()).select_from(models.RawReport).where(models.RawReport.site_id == site_id)) == 0
            record = await session.get(models.SitePlan, site_id)
            record.plan = "standard" if plan == "free" else "free"
            await session.commit()
            for table in (models.DpWindow, models.BreakdownRollup, models.SegmentRollup):
                rows = (await session.scalars(select(table).where(table.site_id == site_id,
                                                                 published_plan_clause(table, record.plan)))).all()
                assert rows
                assert {row.plan for row in rows} == {plan}
            # An aggregate-only upload cannot reconstruct a purged live day.
            assert watermark.dp_window_count > 0 and watermark.breakdown_rollup_count > 0
            overlaps, replaceable = await imports._find_existing_import_overlaps(
                session=session, site_id=site_id,
                rows_by_key={(day, "revenue"): HistoricalImportRow(day=day, metric="revenue", value=50)},
            )
            assert any(row.day == day and row.metric == "revenue" for row in overlaps)
            assert not replaceable
    asyncio.run(check())


def test_reducer_day_lock_is_exclusive_across_transactions():
    from app.scheduler.nightly_reduce import _lock_site_day

    async def check():
        acquired = asyncio.Event()
        async with models.async_session_factory() as first:
            await _lock_site_day(first, "pg-lock", dt.date(2026, 9, 1))

            async def contender():
                async with models.async_session_factory() as second:
                    await _lock_site_day(second, "pg-lock", dt.date(2026, 9, 1))
                    acquired.set()
                    await second.commit()

            task = asyncio.create_task(contender())
            try:
                await asyncio.sleep(0.1)
                assert not acquired.is_set()
            finally:
                await first.rollback()
            await asyncio.wait_for(task, 5)
            assert acquired.is_set()
    asyncio.run(check())


def test_password_reset_token_is_consumed_once_under_concurrency():
    import hashlib
    from fastapi import HTTPException, Response
    from starlette.requests import Request
    from app.routers import password_recovery as recovery

    async def check():
        token = "test-concurrent-reset-token-0000000000"
        async with models.async_session_factory() as session:
            session.add(models.PasswordReset(token_hash=hashlib.sha256(token.encode()).hexdigest(),
                                             username="existing", expires_at=dt.datetime.now(dt.timezone.utc) + dt.timedelta(minutes=5)))
            await session.commit()

        async def confirm():
            async with models.async_session_factory() as session:
                try:
                    await recovery.confirm_reset(recovery.ResetConfirm(token=token, password="new-synthetic-password"),
                                                 Request({"type": "http", "client": ("127.0.0.1", 1)}), Response(), session)
                    return 200
                except HTTPException as exc:
                    return exc.status_code

        assert sorted(await asyncio.gather(confirm(), confirm())) == [200, 400]
        async with models.async_session_factory() as session:
            assert (await session.get(models.DashboardUser, "existing")).auth_version == 1
    asyncio.run(check())


def test_import_preview_and_rollback_preserve_untouched_days(monkeypatch):
    from app.routers import imports
    from app.scheduler import nightly_reduce as reducer
    from app.schemas import HistoricalImportRequest, HistoricalImportRow
    monkeypatch.setattr(reducer.settings, "RAW_REPORT_RETENTION_HOURS", 24 * 365)

    async def check():
        await seed_owner("pg-import")
        site_id = "pg-import-0"
        day1, day2, day3 = (dt.date(2026, 9, number) for number in (10, 11, 12))
        async with models.async_session_factory() as session:
            first = await imports._import_rows(HistoricalImportRequest(site_id=site_id, rows=[
                HistoricalImportRow(day=day1, metric="pageviews", value=100),
                HistoricalImportRow(day=day3, metric="pageviews", value=200),
            ]), session, "standard", {"sub": "pg-import"})
            middle = await imports._import_rows(HistoricalImportRequest(site_id=site_id, rows=[
                HistoricalImportRow(day=day2, metric="pageviews", value=150),
            ]), session, "standard", {"sub": "pg-import"})
            conflicts, replaceable = await imports._find_existing_import_overlaps(
                session=session, site_id=site_id,
                rows_by_key={(day1, "pageviews"): HistoricalImportRow(day=day1, metric="pageviews", value=101)},
            )
            assert not conflicts and replaceable
            before = await session.scalar(select(models.DpWindow.value).where(
                models.DpWindow.site_id == site_id, models.DpWindow.metric == "pageviews",
                models.DpWindow.window_start == dt.datetime.combine(day2, dt.time(), tzinfo=dt.timezone.utc)))
            assert before is not None
            response = await imports.rollback_import_batch(first.batch_id, site_id, {"sub": "pg-import"}, session)
            assert response.deleted_rows == 2
            windows = (await session.scalars(select(models.DpWindow).where(
                models.DpWindow.site_id == site_id, models.DpWindow.metric == "pageviews"))).all()
            assert [(row.window_start.date(), row.value) for row in windows] == [(day2, before)]
            assert (await session.get(models.HistoricalImportBatch, middle.batch_id)).status == "completed"
    asyncio.run(check())


def test_published_history_and_daily_insights_ignore_database_timezone():
    from app.report_history import published_plan_clause
    from app.routers.insights import _daily_metric_totals

    async def check():
        start = dt.datetime(2026, 8, 1, tzinfo=dt.timezone.utc)
        async with models.async_session_factory() as session:
            for plan, value in (("free", 100), ("standard", 999)):
                session.add(models.DpWindow(site_id="pg-timezone", plan=plan, metric="pageviews",
                                            window_start=start, window_end=start + dt.timedelta(days=1),
                                            value=value, variance=0, ci80_low=value, ci80_high=value,
                                            ci95_low=value, ci95_high=value))
            session.add(models.ReducerWatermark(site_id="pg-timezone", plan="free", day=start.date(),
                                                reducer_version="rollups-v1", status="success", raw_report_count=1,
                                                dp_window_count=1, breakdown_rollup_count=1, reduced_at=start))
            await session.commit()
            for timezone in ("America/Chicago", "UTC", "Pacific/Auckland"):
                await session.execute(text("SELECT set_config('TimeZone', :timezone, true)"), {"timezone": timezone})
                values = (await session.scalars(select(models.DpWindow.value).where(
                    models.DpWindow.site_id == "pg-timezone", published_plan_clause(models.DpWindow, "standard")))).all()
                assert values == [100]
                totals = await _daily_metric_totals(session=session, site_id="pg-timezone", plan="free", metric="pageviews",
                                                    start_day=start.date(), end_day=start.date())
                assert totals == {start.date(): 100}
    asyncio.run(check())
