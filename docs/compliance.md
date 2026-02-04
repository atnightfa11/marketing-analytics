# DPIA Summary and Privacy Notice Language

## Data Protection Impact Assessment (DPIA) Highlights

- **Purpose**: Provide aggregate marketing KPIs, anomaly flags, and forecasts without processing identifiable personal data. Privacy guarantees vary by plan and are enforced in the pipeline.
- **Lawfulness**: Analytics relies on legitimate interests with strong privacy safeguards. No raw identifiers are stored or processed server-side.
- **Data Minimization**: The SDK removes IP, UA, cookies, referrers, and deterministic identifiers. Only coarse timestamps and aggregated signals are retained.
- **Tiered DP Controls**:
  - Free: raw aggregates computed from non-identifying payloads (no local DP).
  - Standard DP: aggregate-noise DP is applied server-side with daily epsilon tracking.
  - Pro: local DP randomized response is applied client-side; only privatized bits reach the backend.
- **Storage & Retention**: Reports are stored in Postgres. Raw batches are retained only as needed for reduction; aggregates and forecast outputs are retained per business requirements.
- **Security Controls**:
  - Short-lived upload tokens (900s default) with Argon2id-hashed revocation records.
  - Replay protection via nonce (`jti`) tracking.
  - Unified token bucket rate limiting per site and IP.
  - HSTS and CSP enforced on API and dashboard.
  - Structured audit logs for authentication failures.
- **Risk Mitigations**: Publishing guards require minimum report counts and SNR > 1.5 to suppress noisy metrics. Forecasts require ≥60 days of data, and model promotion needs ≥5% MAPE improvement.

## Privacy Notice Boilerplate

> We collect anonymized marketing analytics without storing IPs, cookies, or unique identifiers. Depending on plan, data is either aggregated server-side with differential privacy noise (Standard) or randomized locally in your browser before transmission (Pro). Free sites use raw aggregates derived from non-identifying payloads. Reports are shuffled, delayed, and aggregated to provide high-level KPIs and anomaly alerts. Tokens expire quickly, and we enforce strict thresholds before publishing any metric. You can disable analytics in your site settings at any time.
