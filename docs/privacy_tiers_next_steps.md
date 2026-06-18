# Privacy Tiers Next Steps

## Completed in this phase

- Standard uses central-DP Laplace aggregate noise for selected high-volume KPI releases in the reducer.
- Standard sessionization remains coarse HMAC-based and replay-resistant.
- Budget tooling split by tier model via script `--tier` flags.
- Docs updated to distinguish Standard (central DP) vs Pro (local DP RR).

## Public Claim Boundary

Standard can be described as using data minimization, short-lived raw processing, aggregate reporting, suppression thresholds, and differential privacy controls for selected high-volume KPI metrics where accuracy remains useful.

Do not describe the entire dashboard as differentially private. Breakdown panels currently use aggregate rollups plus suppression thresholds. Pro/Enterprise local-DP language should remain hidden until the Pro path is enabled, tested, and supported commercially.

## Deferred to Pro/Enterprise v2

- Zero-access local/hybrid DP defaults.
- Dimension-capable local-DP sparse histogram pipelines.
- Top-N dimension results with privacy gating:
  - return rows only when SNR/threshold checks pass
  - otherwise return "Insufficient data for privacy"
- Separate UI messaging for privacy-gated dimension panels.

## Calculator ownership by tier

- Standard calculator: central-DP Laplace utility/error sizing.
- Pro calculator: local-DP RR utility/error sizing.
