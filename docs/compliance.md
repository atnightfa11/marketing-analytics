# DPIA Summary and Privacy Notice Language

## Data Protection Impact Assessment (DPIA) Highlights

- **Purpose**: Provide aggregate marketing KPIs, anomaly flags, and forecasts while minimizing visitor data collection. Privacy guarantees vary by plan and are enforced in the pipeline.
- **Lawfulness**: Analytics relies on legitimate interests with strong privacy safeguards. No direct personal identifiers are stored server-side; transient request metadata is processed only to derive coarse buckets and rotating HMAC keys.
- **Data Minimization**: The SDK stores no cookies or browser local-storage identifiers, honors browser privacy signals (DNT/GPC) by default, and strips click-id parameters (e.g. `gclid`, `msclkid`, `fbclid`) from tracked page URLs while preserving UTM/source campaign tags. The backend stores only coarse dimensions (path, source bucket/domain, device, country) plus short-lived HMAC keys that rotate by session window/day for aggregation. If edge geo headers are unavailable, the server may derive country from request IP using a local GeoIP database and immediately discard the IP (IP is not persisted).
- **Tiered Privacy Controls**:
  - Solo/internal `free`: raw aggregates computed from non-identifying payloads (no local DP).
  - Standard: aggregate-noise DP controls are applied server-side to selected high-volume KPI releases where added noise still preserves useful reporting. Breakdown panels use rollups and suppression thresholds unless a dimension-level DP mechanism is added.
  - Pro: local DP randomized response is applied client-side when the Pro path is enabled; only privatized bits reach the backend.
- **Storage & Retention**: Reports are stored in Postgres. Raw batches are processing material and are purged after successful reducer watermarks plus the configured retention window (`RAW_REPORT_RETENTION_HOURS`, default 72). Solo/internal `free` raw purge is controlled by `FREE_RAW_PURGE_ENABLED` until verified in production. Solo serves 12 months of aggregate analytics history; Standard is intended for forever aggregate retention. KPI aggregates, breakdown rollups, and forecast outputs are durable analytics output retained per business requirements.
- **Security Controls**:
  - Short-lived HMAC-signed upload tokens (900s default) with registered `jti` revocation records.
  - Replay protection via nonce (`jti`) tracking.
  - Unified token bucket rate limiting per site and IP.
  - HSTS and CSP enforced on API and dashboard.
  - Structured audit logs for authentication failures.
  - Site alert settings keep Slack webhook URLs write-only in dashboard APIs. Email alert recipients are stored per site and used only for anomaly notifications.
- **Risk Mitigations**: Publishing guards require minimum report counts and SNR > 1.5 to suppress noisy metrics. Forecasts require enough completed daily history to train, stale forecasts are not served, forecast values are clamped non-negative at the API boundary, and the dashboard shows `Building` instead of accuracy when recent backtests are not useful.

## Privacy Notice Boilerplate

> Valid collects privacy-first marketing analytics without visitor cookies, persistent browser identifiers, or cross-site tracking. By default, the SDK honors browser privacy signals such as Do Not Track (DNT) and Global Privacy Control (GPC), and excludes click-id parameters from tracked page URLs while retaining campaign tags needed for aggregate attribution. Standard uses short-lived raw processing material, aggregate reporting, suppression thresholds, and differential privacy controls for selected high-volume KPI metrics where accuracy remains useful. Reports are aggregated to provide KPIs, forecasts, and anomaly alerts. Tokens expire quickly, and we enforce thresholds before publishing sensitive rows. You can disable analytics in your site settings at any time.

## Public Claim Boundary

Recommended Standard language:

> Valid's Standard tier uses data minimization, aggregate reporting, suppression thresholds, and differential privacy controls for selected high-volume KPI metrics where added noise still preserves useful reporting.

Avoid claiming the whole dashboard is differentially private. Breakdown panels currently use aggregate rollups and suppression thresholds, not a dimension-level DP mechanism.
