# Metrics Definitions

This document defines how API/dashboard metrics are calculated for all plan tiers.

## Plan resolution

- Serving plan is resolved from `site_plan.site_id`.
- If no `site_plan` row exists, serving defaults to `free`.
- `/api/metrics`, `/api/aggregate`, and `/api/forecast` use the resolved plan.

## Metric formulas

- `pageviews`: sum of reduced `pageviews` windows.
- `sessions`:
  - Free: sum of reduced `sessions` events.
  - Standard: unique server-derived HMAC session keys within `SESSION_WINDOW_MINUTES`, then bounded by pageviews in the same session bucket.
  - Pro: reduced LDP estimate from `sessions` randomized-response reports.
- `uniques`: reduced estimate from `uniques` events (presence signal).
- `conversions`: sum of reduced `conversions` events.
- `conversion_rate`: `conversions / pageviews` (derived after aggregation; no extra DP noise term).
- `revenue`: sum of reduced `revenue` events.

Quality notes:

- Metrics publish only after minimum volume and SNR checks in reducers/routes.
- For short windows, sessions are clamped to not exceed pageviews to avoid obviously broken output.
- `conversion_rate` is derived from already published aggregates.
- Standard session dedupe is replay-resistant and coarse-context based.

## Privacy/data handling summary

- No cookies required.
- No raw IP/UA/referrer persistence.
- Standard sessions use a server-side HMAC key from coarse request context and a time bucket.
- Pro remains zero-access local-DP path (no server-side HMAC stitching for Pro).
- Origin checks enforced at token bootstrap and ingest.
- Upload tokens are short-lived.
- Site keys are hashed at rest.
