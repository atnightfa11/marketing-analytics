# Privacy Tiers Next Steps

## Completed in this phase

- Standard uses central-DP Laplace aggregate noise in reducer.
- Standard sessionization remains coarse HMAC-based and replay-resistant.
- Budget tooling split by tier model via script `--tier` flags.
- Docs updated to distinguish Standard (central DP) vs Pro (local DP RR).

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
