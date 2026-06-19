# V1 Readiness Checklist (Updated April 29, 2026)

This checklist reflects what is live in production and what remains before broader public launch.

## Verified working now

- [x] Plan-aware ingestion and serving (`free`, `standard`; `pro` behind flag).
- [x] Central-DP reducer path for Standard.
- [x] Public signup endpoint (`POST /api/public/signup`) for Free + Standard.
- [x] Stripe live checkout session creation for Standard (`/api/checkout/session` and signup checkout URL flow).
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

- [ ] Complete one real Standard checkout and verify webhook plan flip (`site_plan.plan=standard`) for the purchased site.
- [ ] Confirm post-checkout UX on `https://validanalytics.io/signup/complete` (snippet shown, verification clear).
- [ ] Decide final Standard entitlement gates for forecasts, notes, alerts, performance targets, and longer retention before updating Stripe/product copy.
- [ ] Finalize beta-user onboarding policy. Prefer DB-backed site access for ongoing sharing; use `DASHBOARD_SITE_ACCESS_JSON` only for temporary overrides.
- [ ] Decide whether to expose Pro in UI now or keep hidden behind `ENABLE_PRO_INGEST=false`.
- [ ] Keep Pro/Enterprise local-DP claims hidden until the Pro path is enabled, tested, and supported commercially.
- [ ] Run a full launch smoke in production from clean browser:
  - free signup -> dashboard access
  - standard signup -> checkout -> return -> upgraded plan
  - snippet installed -> first data visible

## Required production environment

- [x] `DATABASE_URL`
- [x] `UPLOAD_TOKEN_SECRET`
- [x] `ADMIN_API_TOKEN`
- [x] `COLLECT_ENDPOINT_TOKEN`
- [x] `SESSION_HMAC_SECRET`
- [x] `AGGREGATE_DP_NOISE_SECRET`
- [x] `ENABLE_PROD_SCHEDULER=true`
- [x] `PROD_REDUCER_INTERVAL_MINUTES=60` (or desired hourly cadence)
- [x] `PROD_SCHEDULER_HOUR_UTC`
- [x] `STRIPE_SECRET_KEY` (live)
- [x] `STRIPE_WEBHOOK_SECRET`
- [x] `STRIPE_STANDARD_PRICE_ID`
- [x] `BILLING_ENABLED=true` for commercial production
- [x] `STRIPE_SIGNUP_SUCCESS_URL`
- [x] `STRIPE_SIGNUP_CANCEL_URL`
- [x] `DASHBOARD_ALLOW_UNCLAIMED_SITES=false` (recommended)

## Nice-to-have immediately after launch

- [ ] Alerting for failed reducer/forecast jobs (separate from customer-facing anomaly alerts).
- [x] Expanded migration import docs for history and rollback.
- [ ] Pro/Enterprise v2 privacy docs for zero-access local/hybrid DP.
- [ ] Blog/FAQ explainer for why privacy-first analytics may differ from GA4. Keep this out of onboarding and import settings.
