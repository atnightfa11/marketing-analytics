# V1 Readiness Checklist (Reviewed October 22, 2026)

Implementation status is not deployment evidence. October 21 changes remain local; Railway is available again and the owner will perform deployment. Local tests were rerun October 22, including PostgreSQL 17. See [the release runbook](release_2026_10_21.md) for rollout order, read-only preflight evidence, and remaining verification. Older production checkmarks below are historical observations, not verification of this release.

## October 21 Code Pass

- [x] Protect purged aggregate days from partial imports; require complete retained batches for rollback.
- [x] Preserve published Solo/Standard history across plan changes, including forecast training.
- [x] Account entitlements and retry-safe additional-site setup with explicit $5/month approval.
- [x] Gate unpaid/canceled collection, preserve complimentary beta sites, and prevent grace extension on payment retries.
- [x] Password reset with hashed single-use links, session revocation, and SMTP delivery.
- [x] Cookie-authenticated marketing signup, Solo checkout resume, backend-confirmed completion.
- [x] Read-only deployment checks, schema readiness, release fingerprints, and regression tests.
- [x] Validate the full migration chain and concurrent workflows on isolated local PostgreSQL; fix import date typing and UTC day selection.
- [x] Reconcile current Stripe subscription state under database locks; test delayed/replaced events, retries, and duplicate delivery.
- [x] Repeat local migration/concurrency checks on PostgreSQL 17, matching production's major version; verify SDK lint/tests/build/bundle budget and frontend tests/builds.
- [ ] Rehearse against a production staging copy; owner deploys API, matching worker, dashboard, and marketing site.
- [ ] Complete production payment, signup, password-recovery, and retained-history smoke checks.
- [ ] Complete an isolated backup restore drill and document retention evidence.

## Verified working now

- [x] Plan-aware ingestion and serving (`free`, `standard`; `pro` behind flag).
- [x] Central-DP reducer path for Standard.
- [x] Public signup endpoint (`POST /api/public/signup`) for Solo/internal `free` + Standard.
- [x] Stripe live checkout session creation for Solo, Standard, and optional Early Adopter Standard (`/api/checkout/session` and signup checkout URL flow).
- [x] Stripe webhook endpoint live and signature-validated (`/api/stripe/webhook`).
- [x] Dashboard auth defaults to enabled and site-access authorization hooks present.
- [x] Readiness endpoint checks database and surfaces auth/billing configuration state (`/health/readiness`).
- [x] Site-level tracking health panel/API for recent reports, active key, reducer, aggregate windows, and forecast state.
- [x] Standard import history and rollback for newly tagged import batches while raw import rows are retained.
- [x] Historical import preview with duplicate-row checks, live-overlap warnings, and replaceable-import warnings.
- [x] Plausible-style installation review flow from Settings with one primary Review installation action.
- [x] Owner-managed dashboard site access for existing dashboard users.
- [x] Owner-managed anomaly alert settings for Slack and email destinations.
- [x] Owner-managed performance targets stored server-side for pacing across devices and teammates.
- [x] Reducer cadence supports hourly operation (`PROD_REDUCER_INTERVAL_MINUTES`, default `60`).
- [x] Forecast guardrails: fresh forecasts only, non-negative API output, `Building` state when accuracy is not useful.
- [x] Launch positioning narrowed to privacy-first analytics with forecasting, anomaly context, and goal pacing.

## Still required before broader launch

- [ ] Complete one real Solo checkout and verify webhook links Stripe customer/subscription while `site_plan.plan` remains internal `free`.
- [ ] Complete one real Standard checkout and verify webhook plan flip (`site_plan.plan=standard`) for the purchased site.
- [ ] Confirm post-checkout UX on `https://validanalytics.io/signup/complete` (snippet shown, verification clear).
- [x] Encode revised launch entitlements: Solo ($10) for one site/basic forecasts and continuing aggregate history; Standard ($29) for 3 sites, imports, alerts, all forecast metrics, team/site access, and continuing aggregate history. Capacity allowances are advisory (100K Solo / 1M pooled Standard); increases require customer approval.
- [x] Wire Stripe checkout for Solo, Standard, and optional Early Adopter Standard prices.
- [x] Update Stripe/account billing for $5/additional Standard sites after gates are verified.
- [x] Add Stripe Customer Portal endpoint for self-serve payment method/cancel flows.
- [x] Persist Stripe webhook event IDs for idempotent webhook processing.
- [x] Apply a 7-day payment-failure grace policy before paid entitlements fall back to Solo.
- [ ] Finalize beta-user onboarding policy. Prefer DB-backed site access for ongoing sharing; use `DASHBOARD_SITE_ACCESS_JSON` only for temporary overrides.
- [ ] Verify production Postgres backups/PITR and run a restore drill into staging. Aggregate tables are the durable source of truth after raw purge.
- [x] Keep Pro/Enterprise hidden behind `ENABLE_PRO_INGEST=false`; full LDP is explicitly deferred.
- [ ] Run a full launch smoke in production from clean browser:
  - Solo signup -> checkout -> return -> dashboard access
  - standard signup -> checkout -> return -> upgraded plan
  - snippet installed -> first data visible

## Required production environment

- [x] `DATABASE_URL`
- [x] `UPLOAD_TOKEN_SECRET`
- [x] `ADMIN_API_TOKEN`
- [x] `COLLECT_ENDPOINT_TOKEN`
- [x] `SESSION_HMAC_SECRET`
- [x] `AGGREGATE_DP_NOISE_SECRET`
- [x] `ENABLE_PROD_SCHEDULER=false` on the API when the separate worker service is deployed
- [x] `VALID_PROCESS_TYPE=worker` on the worker service
- [x] `PROD_REDUCER_INTERVAL_MINUTES=60` (or desired hourly cadence)
- [x] `PROD_REDUCER_LOOKBACK_DAYS=7` (recent-day catch-up scan for missing reducer watermarks)
- [x] `PROD_SCHEDULER_HOUR_UTC`
- [x] `FORECAST_TRAIN_ON_STARTUP=true`
- [x] `STRIPE_SECRET_KEY` (live)
- [x] `STRIPE_WEBHOOK_SECRET`
- [x] `STRIPE_SOLO_PRICE_ID`
- [x] `STRIPE_STANDARD_PRICE_ID`
- [x] `BILLING_ENABLED=true` for commercial production
- [x] `STRIPE_SIGNUP_SUCCESS_URL`
- [x] `STRIPE_SIGNUP_CANCEL_URL`
- [x] `DASHBOARD_ALLOW_UNCLAIMED_SITES=false` (recommended)

## Nice-to-have immediately after launch

- [x] Internal reducer/forecast alert code and previously tested email delivery; recheck after deployment.
- [x] Expanded migration import docs for history and rollback.
- [ ] Pro/Enterprise v2 privacy docs for zero-access local/hybrid DP.
- [ ] Blog/FAQ explainer for why privacy-first analytics may differ from GA4. Keep this out of onboarding and import settings.
