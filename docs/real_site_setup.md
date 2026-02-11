# Real Site Setup (Live vs Demo)

Site IDs are internal identifiers; they do not need to match the domain. Use a stable, unique string like:

- Demo: `local-validanalytics-io`
- Live: `live-validanalytics-io`

## Generate an upload token

Run inside the server container:

```bash
docker compose exec server python scripts/create_upload_token.py \
  --site-id live-validanalytics-io \
  --origin https://validanalytics.io
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

## Railway deployment checklist (API)

Set these environment variables on the backend service:

- `DATABASE_URL=postgresql+asyncpg://...`
- `UPLOAD_TOKEN_SECRET=<strong-random-secret>`
- `FORECAST_HORIZON_DAYS=90` (UI can still default to 30-day view)
- `ENABLE_PROD_SCHEDULER=true`
- `PROD_SCHEDULER_HOUR_UTC=2`

Optional tuning:

- `MIN_REPORTS_PER_WINDOW=40`
- `RATE_LIMIT_BUCKET_PER_MIN=200`
- `LIVE_WATERMARK_SECONDS=120`

Stripe billing env vars:

- `STRIPE_SECRET_KEY=sk_test_...`
- `STRIPE_WEBHOOK_SECRET=whsec_...` (from the Dashboard webhook endpoint, not Stripe CLI `listen`)
- `STRIPE_STANDARD_PRICE_ID=price_...`
- `STRIPE_PRO_PRICE_ID=price_...` (optional if Pro is hidden in UI)
- `STRIPE_CHECKOUT_SUCCESS_URL=https://app.validanalytics.io/billing/success`
- `STRIPE_CHECKOUT_CANCEL_URL=https://app.validanalytics.io/billing/cancel`

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

Domain routing:

1. Add `api.validanalytics.io` in Railway Domains.
2. Create DNS CNAME `api` → Railway provided target.
3. Add TXT only if Railway keeps domain verification pending.

## Notes

- Free + Standard are the launch tiers; Pro/LDP is deferred.
- Scheduler behavior:
  - Dev: `ENABLE_DEV_SCHEDULER=1` runs reducer every 60 seconds.
  - Prod: `ENABLE_PROD_SCHEDULER=true` runs daily reducer + daily forecast training.
