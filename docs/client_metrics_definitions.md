# Metrics Definitions

This document defines how API/dashboard metrics are calculated for all plan tiers.

## Plan resolution

- Serving plan is resolved from `site_plan.site_id`.
- If no `site_plan` row exists, serving defaults to `free`, which is the current internal representation for customer-facing Solo.
- `/api/metrics`, `/api/aggregate`, and `/api/forecast` use the resolved plan.
- `/api/aggregate` accepts optional `start` and `end` ISO dates. If omitted, it defaults to a recent bounded window; requests over 730 days are rejected to avoid expensive unbounded reads.

## Metric formulas

- `pageviews`: sum of reduced `pageviews` windows.
- `sessions`:
  - Solo/internal `free`: sum of reduced `sessions` events.
  - Standard: unique server-derived `standard-id-v2` HMAC session keys within `SESSION_WINDOW_MINUTES`, rolled into daily aggregate buckets, then central-DP Laplace noise is added at aggregate publish time.
  - Pro: reduced LDP estimate from `sessions` randomized-response reports.
- `uniques`: reduced estimate from `uniques` events (presence signal). Standard uses a daily `standard-id-v2` HMAC for dedupe. The HMAC input includes site/day, request IP prefix, parsed browser family/major, OS family/major, device class, and a browser/edge timezone hint when available. Raw IP and raw User-Agent are not persisted.
- `conversions`: sum of reduced `conversions` events.
- `conversion_rate`: `conversions / pageviews` (derived after aggregation; no extra DP noise term).
- `revenue`: sum of reduced `revenue` events.

Dashboard-derived engagement metrics:

- `avg_pages_per_visit`: `pageviews / sessions`
- `bounce_rate`: pageview-only estimate based on aggregate counts (single-page-session approximation), does not use conversion events as engagement input.

## GA4 comparison reference

This section is for support, QA, and migration review. It should not be surfaced as a warning in the dashboard UI.

Google Analytics 4 and Valid use similar top-level concepts, but the collection and identity models are different:

| Valid metric | Closest GA4 metric | Comparison notes |
|---|---|---|
| `pageviews` | Views | Closest match. GA4 Views counts repeated page or screen views. Valid counts accepted pageview events after Valid script execution, bot filtering, origin checks, and any plan-specific publish thresholds. |
| `sessions` | Sessions | Similar concept, different sessionization. GA4 sessions begin when a user opens the app/site or views a page with no active session, and default timeout is 30 minutes. Valid Standard uses server-derived `standard-id-v2` HMAC session keys within `SESSION_WINDOW_MINUTES`, then publishes daily aggregate windows. |
| `uniques` | Total users or Users/Active users | Directionally comparable, not equivalent. GA4 Total users counts unique user IDs that triggered events, while GA4 Reports often show Active users as Users. Valid does not use cookies or persistent browser identifiers; Standard uniques use a daily server-derived HMAC and may still differ from GA4 because Valid does not set a persistent client ID. |
| `conversions` | Key events / configured conversion events | Comparable only when both products are configured to fire on the same actions. GA4 key events depend on GA4 event configuration; Valid conversions depend on explicit or auto-conversion capture in the Valid SDK. |
| `revenue` | Purchase revenue / event value | Comparable only when both products receive the same commerce or value events. GA4 purchase revenue is tied to purchase/refund semantics; Valid revenue is the sum of accepted `revenue` events. |

Expected investigation checklist for large aggregate gaps:

1. Confirm date boundaries and timezone match.
2. Compare the same hostname/subdomain scope.
3. Confirm Valid script and GA4 tag are present on the same templates.
4. Check whether consent, ad blockers, tag managers, or CSP rules affect one script but not the other.
5. Confirm conversion/revenue events are configured on the same user actions.
6. Check bot filtering and data-center traffic differences.
7. For Standard, account for aggregate noise, daily publishing, and metric definition differences.

Primary GA4 reference: [Google Analytics dimensions and metrics](https://support.google.com/analytics/answer/9143382).

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
  - Common normalization examples: `google.com -> Google`, `duckduckgo.com -> DuckDuckGo`, `reddit.com -> Reddit`, `x.com`/`t.co -> X`, `linkedin.com -> LinkedIn`, `chatgpt.com -> ChatGPT`, `perplexity.ai -> Perplexity`
  - Fallback bucket mapping: `direct -> Direct`, `external/referral -> Referral`, `organic -> Organic`, `social -> Social`, `email -> Email`, `paid -> Paid`, `ai -> AI Assistants`
  - Dashboard channel grouping is derived from these aggregate source labels. Known search engines become `Organic Search`, known social sites become `Organic Social`, known AI assistant tools become `AI Assistants`, and email/newsletter labels become `Email`.
  - Paid channels require explicit paid evidence such as paid UTM medium (`cpc`, `ppc`, `paid`, `display`, etc.), Google/Bing ad click IDs, or known ad-source labels such as `googleads`/`bingads`. Generic campaign naming does not classify traffic as paid.
  - The dashboard's `Source / Medium` tab is currently an inferred reporting label built from source/channel classification. It is not yet a durable raw `utm_medium` rollup.
- `devices`: from coarse server-derived User-Agent bucket (`mobile`, `desktop`, `tablet`).
- `countries`: from coarse reverse-proxy country headers (for example `CF-IPCountry`) and, when headers are unavailable, optional server-side GeoIP country lookup from request IP. Fallback `Unknown`.
- `hostnames`: from normalized request hostname (`_hostname`) for subdomain-aware reporting.
- `hour_of_day`: from captured timezone hint when available, otherwise the site timezone, aggregated across selected date range.
- `day_of_week`: from captured timezone hint when available, otherwise the site timezone, aggregated across selected date range.

Current caveats:

- Existing historical data may show `Unknown` for device/country until new traffic is ingested.
- Historical import rows are excluded from breakdown dimensions.
- Breakdown rollups are aggregate reporting tables, not raw event storage. They preserve low-dimensional counts by day for customer-facing reporting.
- Time-parting (`hour_of_day`, `day_of_week`) has a minimum range guard:
  - minimum selected range: 7 days
  - `day_type=weekday` and `day_type=weekend` filter rows before aggregation.
- Low-dimensional breakdown rows are not hidden behind k-threshold suppression gates.
- Pro plan currently returns empty dimension rows (aggregate totals only). v2 target: local-DP sparse histograms with top-N + "Insufficient data for privacy" gating.

Quality notes:

- Metrics publish only after minimum volume and SNR checks in reducers/routes.
- Solo served aggregate history is limited to 12 months. Standard aggregate retention is intended to be forever.
- Standard aggregate windows publish daily. Sessions are clamped to not exceed the deduped session baseline after noise to avoid obviously broken output.
- Dashboard date labels preserve the date stamped on full-day aggregate windows. Shorter free/live windows are grouped into days using the site's reporting timezone.
- `conversion_rate` is derived from already published aggregates.
- Standard session dedupe is replay-resistant and based on short-lived, server-derived `standard-id-v2` HMAC keys.
- Standard differential privacy claims apply to selected KPI aggregate windows. Breakdown rows use aggregate rollups unless a future dimension-level DP mechanism is added.
- Forecast training uses completed daily aggregate windows only; the current partial day is excluded from training and backtest scoring.
- Forecast fitting detects large completed-day spikes/drops and excludes those anomaly days from normal seasonality fitting. If the latest completed day is anomalous, `/api/forecast/{metric}` returns `has_anomaly=true`.
- Forecast accuracy is based on count-domain backtesting after any model transform. The dashboard should display an accuracy percentage only when recent backtests are within a useful range; otherwise it should show a building/unstable state.
- Dashboard notes are customer-authored annotations for business context. They do not change aggregate metrics, forecasts, or reducer output.

## Insights

Insights are deterministic summaries derived from the selected KPI period, its comparison period, and reduced aggregate breakdowns.

- Valid only states a driver when one channel, source, page, device, country, or goal-completion type clears contribution and volume thresholds.
- Source rows are also grouped into channel-level evidence so a category such as Organic Search can explain a change even when no single source is dominant.
- If aggregate KPI rows exist for days where matching breakdown rollups are missing, Valid returns an attribution-limited insight instead of ranking incomplete drivers.
- Chart notes can appear as context when they overlap a highlighted period, but notes do not change the analytics totals or the driver calculation.
- If no useful driver or material change is present, `/api/insights` may return an empty list. The dashboard should not replace that with generic filler copy.

## Privacy/data handling summary

- No cookies required.
- No raw IP/UA/referrer persistence.
- Standard sessions use a server-side HMAC key from site scope, request IP prefix, parsed browser/OS/device context, optional timezone hint, and a time bucket.
- Pro remains zero-access local-DP path (no server-side HMAC stitching for Pro).
- Origin checks enforced at token bootstrap and ingest.
- Upload tokens are short-lived.
- Site keys are hashed at rest.
