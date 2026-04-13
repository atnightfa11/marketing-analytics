#!/usr/bin/env python3
from __future__ import annotations

import argparse
import math


def adjusted_probability(epsilon: float, sampling_rate: float) -> tuple[float, float]:
    p = math.exp(epsilon) / (1 + math.exp(epsilon))
    q = 1 - p
    baseline = 0.5
    p_adj = sampling_rate * p + (1 - sampling_rate) * baseline
    q_adj = sampling_rate * q + (1 - sampling_rate) * baseline
    return p_adj, q_adj


def required_epsilon_pro_local_dp(target_relative_error: float, sampling_rate: float, reports: int) -> float | None:
    epsilon = 0.05
    while epsilon < 10.0:
        p, q = adjusted_probability(epsilon, sampling_rate)
        denominator = p - q
        if denominator == 0:
            epsilon += 0.05
            continue
        variance = reports * (1 - p) * p / (denominator**2)
        se = math.sqrt(max(variance, 0.0))
        rel_error = se / max(reports, 1)
        if rel_error <= target_relative_error:
            return epsilon
        epsilon += 0.05
    return None


def required_epsilon_standard_central_dp(target_relative_error: float, sampling_rate: float, reports: int) -> float:
    effective_reports = max(1.0, reports * max(0.0, min(1.0, sampling_rate)))
    # For Laplace(0, b), sigma = sqrt(2) * b and b = 1/epsilon for count sensitivity 1.
    # Relative error target ~= sigma / effective_reports.
    return math.sqrt(2.0) / max(target_relative_error * effective_reports, 1e-12)


def main() -> int:
    parser = argparse.ArgumentParser(description="Compute minimum epsilon for target relative error by tier.")
    parser.add_argument("target_error", type=float, help="Target relative error (for example 0.1)")
    parser.add_argument("--sampling", type=float, default=1.0, help="Sampling rate in [0,1].")
    parser.add_argument("--reports", type=int, default=100, help="Expected reports in publish window.")
    parser.add_argument(
        "--tier",
        choices=["standard", "pro"],
        default="standard",
        help="Privacy model to solve for: standard=central Laplace, pro=local DP RR.",
    )
    args = parser.parse_args()

    if args.tier == "pro":
        epsilon = required_epsilon_pro_local_dp(args.target_error, args.sampling, args.reports)
        if epsilon is None:
            print("No epsilon under 10.0 meets the target for pro/local-DP assumptions.")
            return 1
        print(f"Tier: pro (local DP RR)")
        print(f"Minimum epsilon: {epsilon:.2f}")
        return 0

    epsilon = required_epsilon_standard_central_dp(args.target_error, args.sampling, args.reports)
    print("Tier: standard (central DP Laplace)")
    print(f"Minimum epsilon: {epsilon:.4f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
