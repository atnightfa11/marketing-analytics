# Privacy Data Contract

This contract defines what each analytics table is allowed to contain and how it should be treated.

## Data Classes

- **Processing material**: short-lived data used to derive aggregate outputs. It may include coarse payload fields and rotating HMAC keys, but not raw IP addresses, raw User-Agent strings, cookies, browser storage IDs, or upload token IDs copied into analytics rows.
- **Durable analytics output**: aggregate reporting tables used by dashboards and forecasts.
- **Customer-authored context**: notes or annotations written by dashboard users to explain business events. These records are not analytics events and must not contain raw visitor data.
- **Security/operational data**: authentication, authorization, token, nonce, job status, and billing records.

## Tables

| Table | Class | Allowed contents | Retention target |
|---|---|---|---|
| `raw_reports` | Processing material | Site, metric kind, event day, coarse payload fields, rotating session/day HMACs, device bucket, country code, timezone hint, hostname, normalized page/source/conversion fields | Rows purge after successful reducer watermark and retention window. Default primary retention is 72 hours after reduction. Solo/internal `free` raw purge is guarded by `FREE_RAW_PURGE_ENABLED` until verified in production. |
| `ldp_reports` | Processing material | Local-DP randomized-response payloads for Pro when enabled | Retention policy to be finalized before Pro public claims. |
| `dp_windows` | Durable analytics output | Daily/windowed KPI aggregates, variance, confidence intervals, plan, metric | Business reporting retention. |
| `breakdown_rollups` | Durable analytics output | Low-dimensional aggregate rows by site, plan, day, dimension, hostname scope, day type, label, metric, value | Business reporting retention. This table must not contain raw payloads, IPs, User-Agent strings, visitor IDs, session IDs, upload token IDs, full referrer URLs, or full query strings. |
| `reducer_watermarks` | Operational accountability | Site/day/plan reducer status, reducer version, raw count, output counts, reduction time, purge time | Operational retention. |
| `historical_import_batches` | Operational accountability | Import batch ID, site, source, status, aggregate row count, date range, metric names, dashboard username, timestamps, error text | Operational retention. This table must not contain imported raw payloads, visitor data, IPs, User-Agent strings, or customer analytics values. |
| `forecasts` / `model_store` | Durable analytics output | Forecast outputs and model metadata derived from aggregate windows | Business reporting retention. |
| `dashboard_notes` | Customer-authored context | Site, date, optional metric, note body, dashboard username, timestamps | Customer-controlled business context retention. Notes must not store raw visitor identifiers, raw payloads, IPs, User-Agent strings, or upload token IDs. |
| `site_goals` | Customer-authored context | Site, metric, target, period, repeat cadence, dashboard usernames, timestamps | Customer-controlled performance target retention. Goals are business settings, not analytics events, and must not store raw visitor identifiers, raw payloads, IPs, User-Agent strings, or upload token IDs. |
| `dashboard_site_access` | Security/operational data | Site ID, dashboard username, role, creator username, creation timestamp | Retain while access is active; delete when access is revoked. |
| `upload_tokens` / `token_nonce` | Security/operational data | Token revocation records and replay nonces | Tokens purge after expiry grace; nonces purge after short replay window. Never copy token IDs into analytics rollups. |

## Dashboard Output Rules

- KPI trend endpoints read from `dp_windows`.
- Breakdown endpoints read from `breakdown_rollups` for days with successful reducer watermarks, falling back to bounded `raw_reports` only for unreduced days.
- Sparse breakdown output remains threshold-gated before response.
- Historical import rows are aggregate-only and excluded from dimension rollups.
- Historical import rollback is available only while tagged processing rows remain in `raw_reports`. After purge, `historical_import_batches` is an audit record only.
- Dashboard notes are displayed as annotations only. They must not alter KPI aggregates, breakdown rollups, forecasts, or anomaly scoring.
- Site goals are displayed as pacing targets only. They must not alter KPI aggregates, breakdown rollups, forecasts, anomaly scoring, or import reduction.

## Plan Retention Boundary

Solo serves 12 months of durable aggregate analytics history. Standard is intended for forever aggregate retention. The current database value `free` is the internal Solo representation.

## Differential Privacy Claim Boundary

Standard can claim differential privacy controls only for selected KPI aggregates released through `dp_windows`.

Current breakdown outputs use aggregation and suppression thresholds. They should not be described as differentially private unless a DP mechanism, contribution bounds, and accounting are added for those dimensions.

## Purge Invariant

`raw_reports` may be purged only when:

1. A successful `reducer_watermarks` row exists for the same `site_id`, `plan`, `day`, and reducer version.
2. The reducer wrote KPI windows and breakdown rollups for that day.
3. The retention window has elapsed.
4. Only rows received at or before the successful reduction time are deleted.
5. The site's current plan still matches the watermark plan.

This prevents late-arriving rows from being deleted before a later reducer pass can include them.
