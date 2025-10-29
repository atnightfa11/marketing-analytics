from __future__ import annotations

import math
from typing import Tuple

from ..config import get_settings

settings = get_settings()


def prob_true(epsilon: float) -> Tuple[float, float]:
    exp = math.exp(epsilon)
    p = exp / (1 + exp)
    q = 1 - p
    return p, q


def adjusted_probability(epsilon: float, sampling_rate: float) -> Tuple[float, float]:
    p, q = prob_true(epsilon)
    baseline = 0.5
    p_adj = sampling_rate * p + (1 - sampling_rate) * baseline
    q_adj = sampling_rate * q + (1 - sampling_rate) * baseline
    return p_adj, q_adj


def rr_unbiased_estimate(
    ones: float,
    total: float,
    epsilon: float,
    sampling_rate: float,
    alpha: float | None = None,
) -> Tuple[float, float]:
    alpha = alpha if alpha is not None else settings.ALPHA_SMOOTHING
    p_adj, q_adj = adjusted_probability(epsilon, sampling_rate)
    denominator = p_adj - q_adj
    if denominator == 0:
        return 0.0, 0.0
    estimate = (ones - total * q_adj) / denominator
    estimate += alpha
    estimate = max(0.0, min(total / max(sampling_rate, 1e-9), estimate))
    variance = (
        total * (1 - p_adj) * p_adj + (max(total, 1.0) - total) * (1 - q_adj) * q_adj
    ) / (denominator**2)
    return estimate, variance


def standard_error(variance: float) -> float:
    return math.sqrt(max(variance, 0.0))


def confidence_interval(estimate: float, se: float, z: float) -> Tuple[float, float]:
    if math.isnan(se):
        se = 0.0
    return estimate - z * se, estimate + z * se
