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
- `SESSION_HMAC_SECRET=<strong-random-secret>` (required for Standard plan ingest)
- `GEOIP_COUNTRY_DB_PATH=/tmp/geoip-country.mmdb` (optional; path where API reads/writes GeoIP MMDB)
- `GEOIP_COUNTRY_DB_URL=https://download.db-ip.com/free/dbip-country-lite-{year_month}.mmdb.gz` (optional; startup auto-download)
- `GEOIP_COUNTRY_DB_DOWNLOAD_TIMEOUT_SECONDS=20` (optional; startup download timeout)
- `AGGREGATE_DP_NOISE_SECRET=<strong-random-secret>` (recommended for stable central-DP noise in Standard)
- `RAW_REPORT_RETENTION_HOURS=72` (default; raw reports purge after successful reducer watermarks and this retention window)
- `ADMIN_API_TOKEN=<strong-random-secret>` (required for privileged admin/token endpoints)
- `COLLECT_ENDPOINT_TOKEN=<strong-random-secret>` (required for `/api/collect`; mock-shuffle must send `X-Collect-Token`)
- `SESSION_WINDOW_MINUTES=30`
- `BOT_FILTER_ENABLED=true` (recommended; drops likely bot traffic before storage)
- `BOT_FILTER_MIN_CF_SCORE=30` (if `CF-Bot-Score`/`X-Bot-Score` header is present and below this value, request is filtered)
- `BOT_FILTER_UA_PATTERNS_CSV=` (optional comma-separated extra User-Agent substrings to filter)
- `DASHBOARD_AUTH_ENABLED=true` (set `false` only for local/dev)
- `DASHBOARD_AUTH_USERNAME=<dashboard-admin-username>`
- `DASHBOARD_AUTH_PASSWORD=<dashboard-admin-password>`
- `DASHBOARD_AUTH_USERS_JSON={"alice":"pw1","bob":"pw2"}` (optional, recommended for friend beta; when set, this overrides single-user username/password)
- `DASHBOARD_AUTH_SECRET=<strong-random-secret>`
- `DASHBOARD_ALLOWED_SITE_IDS=<comma-separated-site-ids>` (optional, recommended for ownership auth on `site_id` endpoints)
- `DASHBOARD_SITE_ACCESS_JSON={"username":["site-a","site-b"]}` (optional per-user ownership mapping; explicit user mappings take precedence over `DASHBOARD_ALLOWED_SITE_IDS`, and unmapped users fall back to DB ownership checks)
- `DASHBOARD_ALLOW_UNCLAIMED_SITES=false` (recommended for public launch; set `true` only as a temporary fallback while migrating legacy demo sites)
- `FORECAST_HORIZON_DAYS=90` (UI can still default to 30-day view)
- `ENABLE_PROD_SCHEDULER=true`
- `PROD_SCHEDULER_HOUR_UTC=2`
- `PROD_REDUCER_INTERVAL_MINUTES=60` (hourly reducer cadence)

Optional tuning:

- `MIN_REPORTS_PER_WINDOW=40`
- `RATE_LIMIT_BUCKET_PER_MIN=200`
- `LIVE_WATERMARK_SECONDS=120`

Privileged endpoint headers:

- `POST /api/upload-token` and `POST /api/admin/*` require `X-Admin-Token`.
- `POST /api/collect` requires `X-Collect-Token` (or `ADMIN_API_TOKEN` when `COLLECT_ENDPOINT_TOKEN` is unset).
- Dashboard-protected reads (for example `/api/metrics`, `/api/aggregate`, `/api/breakdown`, `/api/forecast/{metric}`, `/api/jobs/status`) require `Authorization: Bearer <token>` from `/api/auth/login`.

Stripe billing env vars:

- `STRIPE_SECRET_KEY=sk_live_...` (production; use `sk_test_...` only in non-prod environments)
- `STRIPE_WEBHOOK_SECRET=whsec_...` (from the Dashboard webhook endpoint, not Stripe CLI `listen`)
- `STRIPE_STANDARD_PRICE_ID=price_...`
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
  - `plan` (`standard` or `pro`)

Public signup endpoint:

- `POST /api/public/signup`
- Request body:
  - `username`, `email`, `password`
  - `site_name`, `site_domain`
  - `plan` (`free` or `standard`)
- Behavior:
  - `free`: returns `201` with `requires_checkout=false`
  - `standard`: returns `201` with `requires_checkout=true` and `checkout_url`

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

Example per-user beta config:

```text
DASHBOARD_AUTH_USERS_JSON={"heather":"strongpass1","friend1":"strongpass2","friend2":"strongpass3"}
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

- Free + Standard are the launch tiers; Pro/LDP is deferred.
- Scheduler behavior:
  - Dev: `ENABLE_DEV_SCHEDULER=1` runs reducer every 60 seconds.
  - Prod: `ENABLE_PROD_SCHEDULER=true` runs reducer every `PROD_REDUCER_INTERVAL_MINUTES` (default 60) + daily forecast training at `PROD_SCHEDULER_HOUR_UTC`.
