from __future__ import annotations

import math
from typing import Iterable


def ewma(values: Iterable[float], span: float) -> list[float]:
    alpha = 2 / (span + 1)
    smoothed: list[float] = []
    prev = None
    for value in values:
        prev = value if prev is None else alpha * value + (1 - alpha) * prev
        smoothed.append(prev)
    return smoothed


def z_score(value: float, mean: float, variance: float) -> float:
    if variance <= 0:
        return 0.0
    return (value - mean) / math.sqrt(variance)
