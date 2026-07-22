# Real Site Setup (Live vs Demo)

Site IDs are internal identifiers; they do not need to match the domain. Use a stable, unique string like:

- Demo: `local-validanalytics-io`
- Live: `live-validanalytics-io`

## Generate an upload token

Run inside the server container:

```bash
docker compose exec server python scripts/create_upload_token.py \
  --site-id live-validanalytics-io \
  --origin https://validanalytics.io \
  --plan standard
```

This prints a token and a starter SDK snippet.

## Host the SDK bundle

The SDK build lives at `client/dist/index.js`. Host it on your site (for example at `/sdk/index.js`), then use the snippet from the token script.

If you need to rebuild:

```bash
npm --prefix client run build
```

## Dashboard views

Demo dashboard (seeded data):

- `http://localhost:5173` (uses `VITE_SITE_ID=local-validanalytics-io`)

Live dashboard (real traffic):

- `http://localhost:5174` (uses `VITE_SITE_ID=live-validanalytics-io`)
- Hosted app behavior:
  - Root (`/`) is demo-first.
  - Explicit site context (`?site_id=<id>` or `/site/<id>`) uses live KPI/chart totals plus real dimension breakdowns from `/api/breakdown`.
  - Demo seeded breakdowns stay on root mode only.

## Railway deployment checklist (API)

Set these environment variables on the backend service:

- `DATABASE_URL=postgresql+asyncpg://...`
- `UPLOAD_TOKEN_SECRET=<strong-random-secret>`
- `APP_ENV=production`
- `SESSION_HMAC_SECRET=<strong-random-secret>` (required for Standard plan ingest)
- `SESSION_HMAC_IP_PREFIX_V4=32` (default; Standard visitor/session HMAC input uses full IPv4 before discarding raw IP)
- `SESSION_HMAC_IP_PREFIX_V6=64` (default; Standard visitor/session HMAC input uses IPv6 /64 before discarding raw IP)
- `GEOIP_COUNTRY_DB_PATH=/tmp/geoip-country.mmdb` (optional; path where API reads/writes GeoIP MMDB)
- `GEOIP_COUNTRY_DB_URL=https://download.db-ip.com/free/dbip-country-lite-{year_month}.mmdb.gz` (optional; startup auto-download)
- `GEOIP_COUNTRY_DB_DOWNLOAD_TIMEOUT_SECONDS=20` (optional; startup download timeout)
- `AGGREGATE_DP_NOISE_SECRET=<strong-random-secret>` (recommended for stable central-DP noise in Standard)
- `RAW_REPORT_RETENTION_HOURS=72` (default; raw reports purge after successful reducer watermarks and this retention window)
- `FREE_RAW_PURGE_ENABLED=false` initially; set to `true` only after verifying Free/Solo rollup-backed dashboard reads in production
- `ADMIN_API_TOKEN=<strong-random-secret>` (required for privileged admin/token endpoints)
- `COLLECT_ENDPOINT_TOKEN=<strong-random-secret>` (required for `/api/collect`; mock-shuffle must send `X-Collect-Token`)
- `SESSION_WINDOW_MINUTES=30`
- `BOT_FILTER_ENABLED=true` (recommended; drops likely bot traffic before storage)
- `BOT_FILTER_MIN_CF_SCORE=30` (if `CF-Bot-Score`/`X-Bot-Score` header is present and below this value, request is filtered)
- `BOT_FILTER_UA_PATTERNS_CSV=` (optional comma-separated extra User-Agent substrings to filter)
- `DASHBOARD_AUTH_ENABLED=true` (set `false` only for local/dev)
- `DASHBOARD_AUTH_SECRET=<strong-random-secret>`
- `DASHBOARD_AUTH_COOKIE_NAME=valid_dashboard_session`
- `DASHBOARD_AUTH_COOKIE_SECURE=` (leave unset; production infers `true`, local/dev infers `false`)
- `DASHBOARD_AUTH_COOKIE_SAMESITE=lax`
- `DASHBOARD_CORS_ORIGINS_CSV=https://app.validanalytics.io,https://validanalytics.io` (trusted origins allowed to send the dashboard auth cookie; do not add customer sites)
- Dashboard users should live in `dashboard_users` with Argon2 password hashes. Do not configure production dashboard passwords in env vars.
- `DASHBOARD_ALLOWED_SITE_IDS=<comma-separated-site-ids>` (optional, recommended for ownership auth on `site_id` endpoints)
- `DASHBOARD_SITE_ACCESS_JSON={"username":["site-a","site-b"]}` (optional per-user ownership mapping; explicit user mappings take precedence over `DASHBOARD_ALLOWED_SITE_IDS`, and unmapped users fall back to DB ownership checks)
- `DASHBOARD_ALLOW_UNCLAIMED_SITES=false` (recommended for public launch; set `true` only as a temporary fallback while migrating legacy demo sites)
- `FORECAST_HORIZON_DAYS=90` (UI can still default to 30-day view)
- `ALERT_EMAIL_SMTP_HOST=` (optional; required for outbound email anomaly alerts)
- `ALERT_EMAIL_SMTP_PORT=587`
- `ALERT_EMAIL_SMTP_USERNAME=` (optional, depending on provider)
- `ALERT_EMAIL_SMTP_PASSWORD=` (optional, depending on provider)
- `ALERT_EMAIL_FROM=alerts@validanalytics.io` (required with `ALERT_EMAIL_SMTP_HOST`)
- `ALERT_EMAIL_USE_TLS=true`
- `ALERT_WEBHOOK_TOKEN=<strong-random-secret>` (required for authenticated internal `/api/alert/webhook`)
- `OPS_ALERT_WEBHOOK_URL=` (optional Slack/ops webhook destination for reducer/forecast/API alerts)
- `OPS_ALERT_EMAIL_RECIPIENTS_CSV=` (optional comma-separated internal ops recipients; uses the same SMTP settings above)
- `OPS_ALERT_DEDUP_SECONDS=300`
- `METRICS_PUBLIC=false` (recommended; unauthenticated `/metrics` is hidden when no token is configured)
- `METRICS_AUTH_TOKEN=<strong-random-secret>` (optional; allows Prometheus scrapes with `X-Metrics-Token` or `Authorization: Bearer`)
- `ENABLE_PROD_SCHEDULER=false` on the API service when a separate worker is deployed
- `PROD_SCHEDULER_HOUR_UTC=2`
- `PROD_REDUCER_INTERVAL_MINUTES=60` (hourly reducer cadence)
- `PROD_REDUCER_LOOKBACK_DAYS=7` (recent-day catch-up scan for raw days missing a successful reducer watermark)
- Worker service: `VALID_PROCESS_TYPE=worker`

Optional tuning:

- `MIN_REPORTS_PER_WINDOW=40`
- `RATE_LIMIT_BUCKET_PER_MIN=200`
- `LIVE_WATERMARK_SECONDS=120`

Privileged endpoint headers:

- `POST /api/upload-token` and `POST /api/admin/*` require `X-Admin-Token`.
- `POST /api/collect` requires `X-Collect-Token`; it no longer falls back to `ADMIN_API_TOKEN`.
- `GET /metrics` requires `X-Metrics-Token` or `Authorization: Bearer <token>` when `METRICS_AUTH_TOKEN` is configured. Without a metrics token and with `METRICS_PUBLIC=false`, the endpoint returns 404.
- Browser dashboard reads use the `HttpOnly` session cookie set by `/api/auth/login`. Manual scripts can still pass `Authorization: Bearer <token>` from `/api/auth/login` for dashboard-protected reads such as `/api/metrics`, `/api/aggregate`, `/api/breakdown`, `/api/forecast/{metric}`, and `/api/jobs/status`.

Stripe billing env vars:

- `BILLING_ENABLED=true` for commercial production. When enabled, startup requires Stripe secret, webhook secret, Solo price ID, and Standard price ID.
- `STRIPE_SECRET_KEY=sk_live_...` (production; use `sk_test_...` only in non-prod environments)
- `STRIPE_WEBHOOK_SECRET=whsec_...` (from the Dashboard webhook endpoint, not Stripe CLI `listen`)
- `STRIPE_SOLO_PRICE_ID=price_...`
- `STRIPE_STANDARD_PRICE_ID=price_...`
- `STRIPE_EARLY_ADOPTER_STANDARD_PRICE_ID=price_...` (optional; use when offering Early Adopter Standard)
- `STRIPE_PRO_PRICE_ID=price_...` (optional if Pro is hidden in UI)
- `STRIPE_CHECKOUT_SUCCESS_URL=https://app.validanalytics.io/billing/success`
- `STRIPE_CHECKOUT_CANCEL_URL=https://app.validanalytics.io/billing/cancel`
- `STRIPE_SIGNUP_SUCCESS_URL=https://validanalytics.io/signup/complete`
- `STRIPE_SIGNUP_CANCEL_URL=https://validanalytics.io/signup`

Webhook endpoint:

- `POST https://api.validanalytics.io/api/stripe/webhook`
- Subscribe to:
  - `checkout.session.completed`
  - `customer.subscription.created`
  - `customer.subscription.updated`
  - `customer.subscription.deleted`
  - `invoice.payment_failed`

Checkout endpoint:

- `POST /api/checkout/session`
- Request body:
  - `site_id` (your internal site key, for example `live-validanalytics-io`)
  - `plan`:
    - `solo`: customer-facing Solo checkout; persists backend entitlements as internal `free`
    - `standard`: Standard checkout
    - `early_adopter_standard`: Early Adopter Standard checkout; persists backend entitlements as `standard`
    - `pro`: hidden until Pro/LDP is commercially ready

Public signup endpoint:

- `POST /api/public/signup`
- Request body:
  - `username`, `email`, `password`
  - `site_name`, `site_domain`
  - `plan` (`solo`, `standard`, or `early_adopter_standard`; legacy `free` is treated as Solo checkout)
- Behavior:
  - all customer-facing signup plans return `201` with `requires_checkout=true` and `checkout_url`
  - Solo remains stored as backend plan `free` after successful checkout so existing Solo entitlement gates continue to work

Domain routing:

1. Add `api.validanalytics.io` in Railway Domains.
2. Create DNS CNAME `api` → Railway provided target.
3. Add TXT only if Railway keeps domain verification pending.

## Standard plan activation checklist

Standard sessionization is plan-aware. If a site is missing from `site_plan`, it is treated as `free`.

1. Upsert the site plan row:
   ```sql
   insert into site_plan (site_id, plan, updated_at)
   values ('live-neurotypicaltranslator', 'standard', now())
   on conflict (site_id) do update set plan = excluded.plan, updated_at = now();
   ```
2. Ensure `SESSION_HMAC_SECRET` is set on the backend.
3. Regenerate/refresh upload tokens after plan changes so token plan and DB plan match.

Generate a secret locally with:

```bash
openssl rand -hex 32
```

## Anomaly alerts

Site owners can configure anomaly alert destinations in Dashboard Settings -> Anomaly alerts.

- Slack alerts use a site-level Slack incoming webhook URL. The URL is write-only in the API: the dashboard can show that a webhook is saved, but it never receives the saved secret back.
- Email alerts store recipient addresses per site. Outbound email sends only when SMTP env vars are configured on the backend service.
- Alert delivery runs from the forecast refresh path. A site/metric/channel is notified at most once per training day for the same anomaly key.
- Alerts use the same anomaly detector as the forecast chart; they do not add a separate anomaly scoring path.

## Internal ops alerts

Reducer and forecast job failures send internal ops alerts directly from the API/worker process when `OPS_ALERT_WEBHOOK_URL` and/or `OPS_ALERT_EMAIL_RECIPIENTS_CSV` is configured. The authenticated `POST /api/alert/webhook` endpoint uses the same direct delivery path and requires `X-Alert-Token`.

## Installation review

Dashboard Settings -> General -> Site installation should stay compact. Use the **Review installation** button to open the guided setup review instead of exposing the full tracking script or a large health panel inline.

The review flow should show:

- whether the script is sending recent data
- last event received
- detected hostname(s)
- current plan
- reducer status
- forecast status
- anomaly alert setup

Do not expose the deeper operational health panel as a primary customer setting. Keep support/admin diagnosis in logs, readiness checks, and internal ops alerts.

Example per-user beta access config:

```text
DASHBOARD_SITE_ACCESS_JSON={"heather":["*"],"friend1":["site-friend1"],"friend2":["site-friend2"]}
```

## Set Sites Back To Free (Railway Postgres)

If you want to run low-volume sites on Free until traffic grows:

```sql
insert into site_plan (site_id, plan)
values
  ('live-validanalytics-io', 'free'),
  ('live-neurotypicaltranslator', 'free')
on conflict (site_id)
do update set plan = excluded.plan;
```

## Notes

- Solo + Standard are the commercial launch tiers; the current database value `free` is the internal Solo representation. Pro/LDP is deferred.
- Standard includes 3 sites and $5/month additional sites in the product entitlement model. Stripe/account billing for additional sites is a separate follow-up.
- Scheduler behavior:
  - Dev: `ENABLE_DEV_SCHEDULER=1` runs reducer every 60 seconds.
  - Prod API-only mode: `ENABLE_PROD_SCHEDULER=true` runs reducer every `PROD_REDUCER_INTERVAL_MINUTES` (default 60) + daily forecast training at `PROD_SCHEDULER_HOUR_UTC`.
  - Preferred prod split: API runs with `ENABLE_PROD_SCHEDULER=false`; a separate worker service runs the same image with `VALID_PROCESS_TYPE=worker`.
