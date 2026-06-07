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
  - Standard: unique server-derived HMAC session keys within `SESSION_WINDOW_MINUTES`, rolled into daily aggregate buckets, then central-DP Laplace noise is added at aggregate publish time.
  - Pro: reduced LDP estimate from `sessions` randomized-response reports.
- `uniques`: reduced estimate from `uniques` events (presence signal).
- `conversions`: sum of reduced `conversions` events.
- `conversion_rate`: `conversions / pageviews` (derived after aggregation; no extra DP noise term).
- `revenue`: sum of reduced `revenue` events.

Dashboard-derived engagement metrics:

- `avg_pages_per_visit`: `pageviews / sessions`
- `bounce_rate`: pageview-only estimate based on aggregate counts (single-page-session approximation), does not use conversion events as engagement input.

## Dimension breakdowns

- Endpoint: `GET /api/breakdown`
- Serving path: reduced `breakdown_rollups` when available; raw fallback only for unreduced windows.
- Dimensions: `pages`, `sources`, `devices`, `countries`, `conversions`, `hour_of_day`, `day_of_week`, `hostnames`
- Query params:
  - `site_id` (required)
  - `dimension` (required)
  - `start`, `end` (optional ISO dates; if omitted, defaults to last 30 days)
  - `limit` (optional, default `10`)
  - `hostname` (optional exact host filter, for subdomain/site-section views)
  - `day_type` (optional for `hour_of_day`/`day_of_week`; `all`, `weekday`, or `weekend`)

Breakdown definitions:

- `pages`: from pageview `payload.url`, normalized to a path.
- `sources`: from session/pageview/conversion attribution labels using `referrer_source` first, then `referrer_bucket`.
  - Common normalization examples: `google.com -> Google`, `duckduckgo.com -> DuckDuckGo`, `reddit.com -> Reddit`, `x.com`/`t.co -> X`, `linkedin.com -> LinkedIn`
  - Fallback bucket mapping: `direct -> Direct`, `external/referral -> Referral`, `organic -> Organic`, `social -> Social`, `email -> Email`, `paid -> Paid`
- `devices`: from coarse server-derived User-Agent bucket (`mobile`, `desktop`, `tablet`).
- `countries`: from coarse reverse-proxy country headers (for example `CF-IPCountry`) and, when headers are unavailable, optional server-side GeoIP country lookup from request IP. Fallback `Unknown`.
- `hostnames`: from normalized request hostname (`_hostname`) for subdomain-aware reporting.
- `hour_of_day`: from captured timezone hint when available, otherwise the site timezone, aggregated across selected date range.
- `day_of_week`: from captured timezone hint when available, otherwise the site timezone, aggregated across selected date range.

Current caveats:

- Existing historical data may show `Unknown` for device/country until new traffic is ingested.
- Historical import rows are excluded from breakdown dimensions.
- Breakdown rollups are aggregate reporting tables, not raw event storage. They preserve low-dimensional counts by day and continue to enforce response thresholds before returning rows.
- Time-parting (`hour_of_day`, `day_of_week`) has server-side privacy gates:
  - minimum selected range: 7 days
  - bucket suppression: rows require at least 10 sessions
  - `day_type=weekday` and `day_type=weekend` filter rows before privacy gating.
- All breakdown dimensions have suppression gates before response rows are returned:
  - `pages`: minimum 2 pageviews
  - `sources`: minimum 2 sessions
  - `devices`: minimum 2 pageviews
  - `countries`: minimum 1 pageview
  - `conversions`: minimum 2 conversions
  - `hostnames`: minimum 1 session
- Pro plan currently returns empty dimension rows (aggregate totals only). v2 target: local-DP sparse histograms with top-N + "Insufficient data for privacy" gating.

Quality notes:

- Metrics publish only after minimum volume and SNR checks in reducers/routes.
- Standard aggregate windows publish daily. Sessions are clamped to not exceed the deduped session baseline after noise to avoid obviously broken output.
- `conversion_rate` is derived from already published aggregates.
- Standard session dedupe is replay-resistant and coarse-context based.
- Standard differential privacy claims apply to selected KPI aggregate windows. Breakdown rows use aggregate rollups plus suppression thresholds unless a future dimension-level DP mechanism is added.

## Privacy/data handling summary

- No cookies required.
- No raw IP/UA/referrer persistence.
- Standard sessions use a server-side HMAC key from coarse request context and a time bucket.
- Pro remains zero-access local-DP path (no server-side HMAC stitching for Pro).
- Origin checks enforced at token bootstrap and ingest.
- Upload tokens are short-lived.
- Site keys are hashed at rest.
