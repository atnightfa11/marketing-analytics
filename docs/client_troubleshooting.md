# Client Troubleshooting

## CORS errors

**Symptom:** `No 'Access-Control-Allow-Origin' header`

**Fix:**

- Add your site origin to API CORS allow-list (`CORS_ORIGINS_CSV=https://example.com,https://another.com`).
- For short pilot windows only, you can temporarily set `CORS_ALLOW_ALL=true`.
- Ensure request `Origin` matches site key allowed origin pattern.

## 401 Unauthorized

**Symptom:** shuffle/bootstrap returns `401`

**Fix:**

- Verify site key is active.
- Verify upload token has not expired.
- `/api/shuffle` now requires an `Origin` header that matches the token origin pattern.
- SDK automatically refreshes once; if still failing, rotate site key.
- If dashboard auth is enabled, dashboard/API reads require a valid bearer token from `/api/auth/login`:
  - `/api/metrics`
  - `/api/aggregate`
  - `/api/forecast/{metric}`
  - `/api/breakdown`
  - `/api/jobs/status`

## 403 Forbidden

**Symptom:** `Origin not allowed` or `Pro tier is not enabled`

**Fix:**

- Update allowed origin pattern on site key (wildcards are blocked by default).
- Keep `ENABLE_PRO_INGEST=false` for Free/Standard launch.

## 429 Too Many Requests

**Fix:**

- Reduce bootstrap retries.
- Review traffic bursts and plan limits.

## No data in dashboard

1. Confirm `POST /api/shuffle` returns `202`.
2. Run reducer for near-real-time checks:
   ```bash
   python server/run_scheduler.py --days 1
   ```
3. Confirm dashboard `VITE_SITE_ID` matches your `site_id`.

## Breakdown tables show `Unknown`

- Device and country rows are populated from coarse server-side buckets at ingest time.
- Older events may not include these fields; new events will gradually fill real labels.
- Confirm your edge/proxy passes country headers (for example `CF-IPCountry`) if you need country detail, or configure `GEOIP_COUNTRY_DB_URL` (and optional `GEOIP_COUNTRY_DB_PATH`) on the API service for IP-to-country fallback.

## I see pageviews but no sessions

- For Standard tier, sessions are derived from server-side HMAC session keys.
- Ensure `SESSION_HMAC_SECRET` is configured.
- Ensure events are flowing to `/api/shuffle` with `Origin` allowed and reducer has run.

## Auto-conversions not firing

- Confirm `data-valid-autoconversions` is not set to `false`.
- Confirm `data-valid-conversion-selector` matches your explicit conversion nodes.
- For forms, ensure submit event is not prevented before capture.
- Validate in DevTools that conversion events hit `/api/shuffle`.

## CSP blocks SDK

- Allow script source `https://app.validanalytics.io` (or your SDK host) in `script-src`.
- Allow `https://api.validanalytics.io` in `connect-src`.
- If using inline scripts, configure nonce/hash or allow `'unsafe-inline'` for pilot mode.
