
```docs/privacy_budget_calculator.md
# Local DP calculator

RR channel:
- p = exp(ε) / (1 + exp(ε))
- q = 1 − p
Sampling aware helper adjusted_p(ε, s) is provided in server/app/ldp/rr_decoder.py

Unbiased estimate with alpha smoothing:
- N̂ = (s_ones + α − n·q) / (p − q + 2α/n)

Variance and error:
- Var(N̂) = (s·(1 − p)·p + (n − s)·(1 − q)·q) / (p − q)^2
- std_error = sqrt(Var(N̂))
- SNR = N̂ / std_error. Require SNR > 1.5 to publish.

Reference table (approx):
| ε  | expected abs error on 1k true uniques |
| 0.2 | ~90–120 |
| 0.5 | ~45–65  |
| 1.0 | ~25–40  |

Use scripts/calc_budget.py to invert target error to ε.
