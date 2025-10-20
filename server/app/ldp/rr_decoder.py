# Randomized Response decoding helpers with optional Bayesian smoothing and
# sampling-aware parameters

import math
from typing import Tuple

def prob_true(eps: float) -> float:
  e = math.exp(eps)
  return e / (1.0 + e)

def adjusted_p(eps: float, sampling: float) -> Tuple[float, float]:
  """
  Return effective (p, q) under client-side sampling s in [0,1].
  We keep the RR channel parameters and pass sampling separately to the estimator.
  The estimator should use n_effective = n * s for rate calculations where appropriate.
  """
  p = prob_true(eps)
  q = 1.0 - p
  s = min(1.0, max(0.0, sampling))
  return p, q

def rr_unbiased_estimate(
  s_ones: int,
  n_reports: int,
  eps: float,
  alpha: float = 0.5
) -> Tuple[float, float, float]:
  """
  Returns (estimate, variance, std_error) for count of true 1s
  with optional Bayesian smoothing alpha.
  Clamps estimate to [0, n_reports].
  """
  if n_reports <= 0:
    return 0.0, 0.0, 0.0

  p = prob_true(eps)
  q = 1.0 - p
  denom = p - q
  if denom == 0.0:
    return 0.0, 0.0, 0.0

  # Smoothed estimator
  est = (s_ones + alpha - n_reports * q) / (denom + 2.0 * alpha / max(1.0, n_reports))
  est = max(0.0, min(float(n_reports), est))

  # Variance using RR channel moments
  var_num = s_ones * (1 - p) * p + (n_reports - s_ones) * (1 - q) * q
  var = var_num / (denom ** 2)
  se = math.sqrt(max(0.0, var))
  return est, var, se
