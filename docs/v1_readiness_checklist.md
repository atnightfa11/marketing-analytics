# V1 Readiness Checklist (Free + Standard launch)

This checklist reflects the **current repository state** and the shortest path to launch a stable V1.

## 1) Current status snapshot

### Implemented now
- API, reducer, and dashboard are functional for a single ingest path.
- Prophet forecasting job exists with configurable horizon (`FORECAST_HORIZON_DAYS`) and daily scheduler support via `ENABLE_PROD_SCHEDULER`. 
- Dashboard supports metric/range selection and forecast display controls.

### Still pending for true Free + Standard launch
- Plan-aware ingest split is not implemented yet in code (no `raw_reports` ingestion path).
- Data model does not yet include plan-partitioned serving for aggregates/forecasts.
- Integration tests for Free/Standard tier behavior are not complete.
- Historical import pipeline for customer migration is not implemented.

---

## 2) Launch-blocking engineering tasks

### A. Tier data model and ingest branching
- [ ] Add/verify `site_plan` model and migrations.
- [ ] Add `raw_reports` model + migration.
- [ ] Branch ingest:
  - Free/Standard -> store in `raw_reports`
  - Pro (waitlist) -> keep LDP path behind feature flag.
- [ ] Add plan-aware rate limits:
  - Free: 500 daily visits / lower API bucket
  - Standard: 5,000 daily visits / higher bucket.

### B. Reducer and serving
- [ ] Add Free path: raw aggregate publishing.
- [ ] Add Standard path: aggregate-noise DP + epsilon log.
- [ ] Make `/api/metrics`, `/api/aggregate`, `/api/forecast` resolve by site plan.
- [ ] Keep forecast enabled for Standard by default.

### C. Forecast operations
- [ ] Keep default dashboard forecast view at 30 days.
- [ ] Generate enough forecast rows for UI presets (30/60/90 + quarters).
- [ ] Run daily schedule (inside API server for V1).
- [ ] Add job-health logging/alerting.

### D. Imports (required for customer migration)
- [ ] Create CSV import format (date, metric, value minimum).
- [ ] Build import endpoint/script + validation.
- [ ] Re-run reducer/forecast after import.

### E. Tests and release checks
- [ ] Add integration tests for Free + Standard flows.
- [ ] Add scheduler smoke test (daily reduce + forecast).
- [ ] Validate dashboard against both demo site and live site IDs.

---

## 3) Infrastructure and deployment checklist

### Required environment
- [ ] `DATABASE_URL` with async driver (`postgresql+asyncpg://...`).
- [ ] `UPLOAD_TOKEN_SECRET` (rotate before launch if previously shared).
- [ ] `ENABLE_PROD_SCHEDULER=true` and `PROD_SCHEDULER_HOUR_UTC` set.
- [ ] `FORECAST_HORIZON_DAYS=90` (recommended to support quarter presets).

### Domain and routing
- [ ] `api.validanalytics.io` -> Railway backend (CNAME).
- [ ] `app.validanalytics.io` -> dashboard deployment.
- [ ] CORS allow-list includes `https://app.validanalytics.io` and `https://validanalytics.io` where needed.

### Billing (can land after technical go-live prep)
- [ ] Stripe keys and webhook secret.
- [ ] Price IDs for Standard (launch) and Pro (waitlist).
- [ ] Webhook -> update `site_plan`.

---

## 4) Suggested execution order (fastest path)
1. Tier schema + ingest split (`site_plan`/`raw_reports`).
2. Free/Standard reducer + plan-aware serving.
3. Forecast scheduler hardening + horizon coverage for UI presets.
4. Historical import path.
5. Integration test pass + release hardening.

---

## 5) Go-live definition for V1
V1 is ready when all are true:
- Free and Standard data paths both work end-to-end (ingest -> reduce -> serve -> dashboard).
- Daily forecast job runs automatically and returns forecast data for active metrics.
- Historical import works for onboarding at least one external dataset.
- Dashboard can switch between demo site and live site without code changes.
