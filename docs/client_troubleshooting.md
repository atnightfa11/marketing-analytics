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
