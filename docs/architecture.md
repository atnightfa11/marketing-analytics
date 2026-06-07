# Architecture

```mermaid
flowchart LR
    SDK["Browser SDK"] --> Shuffle["/api/shuffle"]
    Shuffle -->|Free + Standard| Raw["raw_reports (Postgres)"]
    Shuffle -->|Pro (if enabled)| Ldp["ldp_reports (Postgres)"]
    Raw --> Reduce["Reducer"]
    Ldp --> Reduce
    Reduce --> Windows["dp_windows"]
    Reduce --> Rollups["breakdown_rollups"]
    Reduce --> Watermarks["reducer_watermarks"]
    Windows --> Forecast["Forecast training"]
    Windows --> API["Metrics API + Dashboard"]
    Rollups --> API
```

Valid uses plan-aware ingest and reduction:

- **Free**: raw aggregates from coarse, non-identifying payloads.
- **Standard**: raw ingest + central-DP aggregate noise at reduce/publish time.
- **Pro**: local-DP (RR) ingest path (currently feature-flagged with `ENABLE_PRO_INGEST`).

## Ingest

- SDK posts shuffled batches to `POST /api/shuffle`.
- API validates short-lived upload token + origin, replay nonce (`jti`), and rate limits.
- Pipeline inserts:
  - `raw_reports` for Free/Standard
  - `ldp_reports` for Pro
- If `ENABLE_PRO_INGEST=false`, Pro requests are treated as Standard for ingest safety.

## Data captured for Free/Standard

For each report, reducer-friendly coarse fields are stored:

- `_session_hmac` (Standard/Free session dedupe key, server-derived)
- `_visitor_day_hmac` (daily unique dedupe key, server-derived)
- `_device_bucket` (`mobile`, `desktop`, `tablet`, `unknown`)
- `_country_code` (2-letter code or `Unknown`)
- `_timezone_hint` when supplied by request infrastructure
- `_hostname` (normalized host for subdomain filtering)
- event payload fields such as `url`, `conversion_type`, `referrer_bucket`, `referrer_source`

Raw IP address and raw User-Agent are used transiently for coarse derivation/HMAC and are not persisted as raw identifiers in report payloads.

## Reducer + publish model

- Reducer writes aggregates to `dp_windows`.
  - Free publishes short reducer windows for live/low-latency dashboard views.
  - Standard publishes daily central-DP aggregate windows for better utility and lower storage/write volume.
- Reducer writes low-dimensional breakdown aggregates to `breakdown_rollups`.
  - Rollups are keyed by site, plan, day, dimension, hostname scope, day type, label, and metric.
  - Dashboard breakdowns prefer rollups and fall back to raw only for windows that have not been reduced yet.
- Reducer writes successful site/day status to `reducer_watermarks`.
  - Standard raw purge uses these watermarks so rows are deleted only after successful reduction.
- Forecast job trains and writes forecast rows from `dp_windows`.
- Production scheduler behavior:
  - reducer interval: `PROD_REDUCER_INTERVAL_MINUTES` (default 60)
  - forecast training: daily at `PROD_SCHEDULER_HOUR_UTC` (+15 minute offset)

## Serving endpoints

- KPI/time series:
  - `GET /api/metrics`
  - `GET /api/aggregate`
  - `GET /api/forecast/{metric}`
- Breakdowns:
  - `GET /api/breakdown`
  - dimensions: `pages`, `sources`, `devices`, `countries`, `conversions`, `hour_of_day`, `day_of_week`, `hostnames`
  - supports `hostname=<host>` filter for subdomain tracking
  - time-parting dimensions support `day_type=all|weekday|weekend`
  - reads from `breakdown_rollups` after reduction

All dashboard metrics endpoints require dashboard auth and site-access authorization.

## Privacy by tier

- **Free**: no DP noise added; privacy comes from data minimization + coarse aggregation + short-lived credentials.
- **Standard**: central DP noise on aggregates plus coarse server-side sessionization.
- **Pro**: local-DP ingest model; dimension breakdowns are currently suppressed for Pro until dimension-capable LDP histograms are enabled.
