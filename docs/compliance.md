# DPIA Summary and Privacy Notice Language

## Data Protection Impact Assessment (DPIA) Highlights

- **Purpose**: Provide aggregate marketing KPIs, anomaly flags, and short-term forecasts without processing identifiable personal data. All data is privatized with local differential privacy before transmission.
- **Lawfulness**: Analytics relies on legitimate interests with strong privacy safeguards. No raw identifiers are stored or processed server-side.
- **Data Minimization**: The client SDK removes IP, UA, cookies, referrer, and any deterministic identifiers. Only randomized response bits and coarse histogram buckets are sent.
- **Storage & Retention**: Reports are stored in a month-partitioned Postgres cluster. DP windows and uniques are retained per business requirements; raw shuffled batches are deleted after reduction.
- **Security Controls**:
  - Short-lived upload tokens (900s default) with Argon2id-hashed revocation records.
  - Replay protection via nonce (`jti`) tracking.
  - Unified token bucket rate limiting per site and IP.
  - HSTS and CSP enforced on API and dashboard.
  - Structured audit logs for authentication failures.
- **Risk Mitigations**: Publishing guards require minimum report counts and SNR > 1.5 to suppress noisy metrics. Forecasts require ≥60 days of data, and model promotion needs ≥5% MAPE improvement.

## Privacy Notice Boilerplate

> We collect anonymized marketing analytics using local differential privacy. Your browser randomly perturbs pageview, session, and conversion signals before sending them; no raw identifiers or precise timestamps leave your device. Reports are shuffled, delayed, and aggregated to provide high-level KPIs and anomaly alerts. Tokens expire quickly, and we enforce strict thresholds before publishing any metric. You can disable analytics in your site settings at any time.
