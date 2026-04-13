#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import math
import random


def adjusted_probability(epsilon: float, sampling_rate: float) -> tuple[float, float]:
    p = math.exp(epsilon) / (1 + math.exp(epsilon))
    q = 1 - p
    baseline = 0.5
    return (
        sampling_rate * p + (1 - sampling_rate) * baseline,
        sampling_rate * q + (1 - sampling_rate) * baseline,
    )


def rr_bit(true_value: bool, epsilon: float, sampling_rate: float, rng: random.Random) -> int:
    p, q = adjusted_probability(epsilon, sampling_rate)
    probability = p if true_value else q
    return 1 if rng.random() < probability else 0


def validate_pro_local_dp(trials: int, epsilon: float, sampling_rate: float) -> dict[str, float | str]:
    rng = random.Random(42)
    successes = 0
    for _ in range(trials):
        successes += rr_bit(True, epsilon, sampling_rate, rng)
    empirical_mean = successes / max(trials, 1)
    theoretical_mean, _ = adjusted_probability(epsilon, sampling_rate)
    return {
        "tier": "pro",
        "model": "local_dp_rr",
        "empirical_mean": empirical_mean,
        "theoretical_mean": theoretical_mean,
    }


def laplace_sample(scale: float, rng: random.Random) -> float:
    u = rng.random()
    if u < 0.5:
        return scale * math.log(2.0 * u)
    return -scale * math.log(2.0 * (1.0 - u))


def validate_standard_central_dp(trials: int, epsilon: float, true_count: float) -> dict[str, float | str]:
    rng = random.SystemRandom()
    scale = 1.0 / max(epsilon, 1e-9)
    samples = [max(0.0, true_count + laplace_sample(scale, rng)) for _ in range(max(trials, 1))]
    empirical_mean = sum(samples) / len(samples)
    empirical_var = sum((value - empirical_mean) ** 2 for value in samples) / len(samples)
    theoretical_var = 2.0 * (scale**2)
    return {
        "tier": "standard",
        "model": "central_dp_laplace",
        "empirical_mean": empirical_mean,
        "empirical_variance": empirical_var,
        "theoretical_variance": theoretical_var,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate privacy-budget assumptions by tier.")
    parser.add_argument("--trials", type=int, default=10000)
    parser.add_argument("--epsilon", type=float, default=0.5)
    parser.add_argument("--sampling", type=float, default=1.0)
    parser.add_argument("--count", type=float, default=100.0, help="True count (standard tier validation).")
    parser.add_argument("--tier", choices=["standard", "pro"], default="standard")
    args = parser.parse_args()

    if args.tier == "pro":
        result = validate_pro_local_dp(args.trials, args.epsilon, args.sampling)
    else:
        result = validate_standard_central_dp(args.trials, args.epsilon, args.count)

    print(json.dumps(result))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
