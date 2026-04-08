# Metrics Definitions

This document defines how the API/dashboard metrics are calculated for Free and Standard.

- **pageviews**: Sum of reduced `pageviews` events in the selected window.
- **sessions**:
  - Free: sum of reduced `sessions` events.
  - Standard: number of unique server-derived HMAC session keys per window (deduped).
- **uniques**: reduced daily presence estimate from `uniques`.
- **conversions**: sum of reduced `conversions` events.
- **conversion_rate**: `conversions / pageviews` (computed after decoding/aggregation).
- **revenue**: sum of reduced `revenue` events.

Quality notes:

- Metrics publish only after minimum volume and SNR checks in reducers/routes.
- For short windows, sessions are clamped to not exceed pageviews to avoid obviously broken output.
- `conversion_rate` is derived from already published aggregates; no extra noise term is added.

## Privacy/data handling summary

- No cookies required.
- No raw IP/UA/referrer persistence.
- Standard sessions use a server-side HMAC key from coarse request context and a time bucket.
- Pro remains zero-access local-DP path (no server-side HMAC stitching for Pro).
- Origin checks enforced at token bootstrap and ingest.
- Upload tokens are short-lived.
- Site keys are hashed at rest.
