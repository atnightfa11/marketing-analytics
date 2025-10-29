# Privacy Budget Calculator

This calculator models randomized response with sampling, alpha smoothing, and publishing guards that require SNR ≥ 1.5. Let:

- `p = exp(ε) / (1 + exp(ε))`
- `q = 1 - p`
- `s` be the sampling probability
- `adjusted_p(ε, s) = s * p + (1 - s) * 0.5`
- `adjusted_q(ε, s) = s * q + (1 - s) * 0.5`

The smoothed unbiased estimator for uniques is 

N_hat = max(0, min(n, (s_ones - n * adjusted_q) / (adjusted_p - adjusted_q) + α)) 

with variance 

Var = (s * (1 - adjusted_p) * adjusted_p + (n - s) * (1 - adjusted_q) * adjusted_q) / (adjusted_p - adjusted_q)^2

Standard error is `sqrt(Var)`, and we publish only when `SNR = N_hat / SE ≥ 1.5`. Confidence intervals follow `estimate ± z * SE` where `z ∈ {1.2816 (80%), 1.9599 (95%)}`.

| ε | p (exp(ε)/(1+exp(ε))) | q | adjusted_p(ε, 0.5) | adjusted_q(ε, 0.5) | 80% CI half-width (z₀.₈ · SE) | 95% CI half-width (z₀.₉₅ · SE) |
|---|-----------------------|---|--------------------|--------------------|--------------------------------|--------------------------------|
| 0.2 | 0.5498 | 0.4502 | 0.5249 | 0.4751 | 1.2816 · SE | 1.9599 · SE |
| 0.5 | 0.6225 | 0.3775 | 0.5612 | 0.4387 | 1.2816 · SE | 1.9599 · SE |
| 1.0 | 0.7311 | 0.2689 | 0.6156 | 0.3845 | 1.2816 · SE | 1.9599 · SE |

Use `scripts/calc_budget.py` to solve for the minimum ε that meets a target relative error given `s`, `n`, and α smoothing. Sampling reduces user contribution frequency, while the local DP constraint ensures no raw identifiers ever leave the browser.
