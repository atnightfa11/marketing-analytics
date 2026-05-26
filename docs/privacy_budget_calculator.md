# Privacy Budget Calculator

This repo now treats privacy-budget sizing as tier-specific:

- `standard`: central DP (server-side Laplace noise on aggregates)
- `pro`: local DP randomized response (RR) decode path

Use `scripts/calc_budget.py --tier ...` and `scripts/validate_privacy_budget.py --tier ...`.

## Standard (Central DP)

For daily aggregate count queries with sensitivity 1:

- Laplace scale: `b = 1 / epsilon`
- Variance: `Var = 2 * b^2`
- Std dev: `sigma = sqrt(2) / epsilon`

Approximate relative error target:

`target_relative_error ~= sigma / effective_reports`

where `effective_reports = reports * sampling_rate`.

Solver:

```bash
python scripts/calc_budget.py 0.10 --tier standard --reports 500 --sampling 1.0
```

Validation simulation:

```bash
python scripts/validate_privacy_budget.py --tier standard --epsilon 1.0 --count 500 --trials 20000
```

## Pro (Local DP RR)

RR parameters:

- `p = exp(epsilon) / (1 + exp(epsilon))`
- `q = 1 - p`
- `adjusted_p = s*p + (1-s)*0.5`
- `adjusted_q = s*q + (1-s)*0.5`

Use this tier when events are privatized in-browser before upload.

Solver:

```bash
python scripts/calc_budget.py 0.10 --tier pro --reports 500 --sampling 0.5
```

Validation simulation:

```bash
python scripts/validate_privacy_budget.py --tier pro --epsilon 1.0 --sampling 0.5 --trials 20000
```

## Notes

- Free tier does not currently add DP noise; it remains privacy-respecting via data minimization (no cookies, no persistent user IDs, coarse metadata handling).
- Standard central DP can be too noisy for very low traffic, but daily aggregate buckets give materially better utility than sparse minute buckets.
