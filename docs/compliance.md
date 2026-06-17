# DPIA Summary and Privacy Notice Language

## Data Protection Impact Assessment (DPIA) Highlights

- **Purpose**: Provide aggregate marketing KPIs, anomaly flags, and forecasts without processing identifiable personal data. Privacy guarantees vary by plan and are enforced in the pipeline.
- **Lawfulness**: Analytics relies on legitimate interests with strong privacy safeguards. No direct personal identifiers are stored server-side; transient request metadata is processed only to derive coarse buckets and rotating HMAC keys.
- **Data Minimization**: The SDK stores no cookies or browser local-storage identifiers, honors browser privacy signals (DNT/GPC) by default, and strips click-id parameters (e.g. `gclid`, `msclkid`, `fbclid`) from tracked page URLs while preserving UTM/source campaign tags. The backend stores only coarse dimensions (path, source bucket/domain, device, country) plus short-lived HMAC keys that rotate by session window/day for aggregation. If edge geo headers are unavailable, the server may derive country from request IP using a local GeoIP database and immediately discard the IP (IP is not persisted).
- **Tiered DP Controls**:
  - Free: raw aggregates computed from non-identifying payloads (no local DP).
  - Standard DP: aggregate-noise DP is applied server-side with daily epsilon tracking.
  - Pro: local DP randomized response is applied client-side; only privatized bits reach the backend.
- **Storage & Retention**: Reports are stored in Postgres. Standard raw batches are processing material and are purged after successful reducer watermarks plus the configured retention window (`RAW_REPORT_RETENTION_HOURS`, default 72). KPI aggregates, breakdown rollups, and forecast outputs are durable analytics output retained per business requirements.
- **Security Controls**:
  - Short-lived HMAC-signed upload tokens (900s default) with registered `jti` revocation records.
  - Replay protection via nonce (`jti`) tracking.
  - Unified token bucket rate limiting per site and IP.
  - HSTS and CSP enforced on API and dashboard.
  - Structured audit logs for authentication failures.
  - Site alert settings keep Slack webhook URLs write-only in dashboard APIs. Email alert recipients are stored per site and used only for anomaly notifications.
- **Risk Mitigations**: Publishing guards require minimum report counts and SNR > 1.5 to suppress noisy metrics. Forecasts require ≥60 days of data, and model promotion needs ≥5% MAPE improvement.

## Privacy Notice Boilerplate

> We collect anonymized marketing analytics without cookies or persistent browser identifiers. By default, the SDK honors browser privacy signals such as Do Not Track (DNT) and Global Privacy Control (GPC), and excludes click-id query parameters from tracked URLs while retaining campaign tags needed for aggregate attribution. Depending on plan, data is either aggregated server-side with differential privacy noise (Standard) or randomized locally in your browser before transmission (Pro). Free sites use raw aggregates derived from coarse, non-identifying payloads and rotating daily/session HMAC keys to avoid persistent tracking. Reports are shuffled, delayed, and aggregated to provide high-level KPIs and anomaly alerts. Tokens expire quickly, and we enforce strict thresholds before publishing any metric. You can disable analytics in your site settings at any time.

## Public Claim Boundary

Recommended Standard language:

> Valid's Standard tier uses data minimization, aggregate reporting, suppression thresholds, and differential privacy controls for selected high-volume KPI metrics where added noise still preserves useful reporting.

Avoid claiming the whole dashboard is differentially private. Breakdown panels currently use aggregate rollups and suppression thresholds, not a dimension-level DP mechanism.
