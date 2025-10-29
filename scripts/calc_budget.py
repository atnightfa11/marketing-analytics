#!/usr/bin/env python3
import argparse
import math

def adjusted_probability(epsilon: float, sampling_rate: float):
    p = math.exp(epsilon) / (1 + math.exp(epsilon))
    q = 1 - p
    baseline = 0.5
    p_adj = sampling_rate * p + (1 - sampling_rate) * baseline
    q_adj = sampling_rate * q + (1 - sampling_rate) * baseline
    return p_adj, q_adj

def required_epsilon(target_relative_error: float, sampling_rate: float, n: int):
    epsilon = 0.05
    while epsilon < 3.0:
        p, q = adjusted_probability(epsilon, sampling_rate)
        denominator = p - q
        variance = n * (1 - p) * p / (denominator ** 2)
        se = math.sqrt(variance)
        rel_error = se / n
        if rel_error <= target_relative_error:
            return epsilon
        epsilon += 0.05
    return None

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Compute minimum epsilon for a target error rate.")
    parser.add_argument("target_error", type=float, help="Target relative error (e.g. 0.1)")
    parser.add_argument("--sampling", type=float, default=0.5)
    parser.add_argument("--reports", type=int, default=100)
    args = parser.parse_args()

    epsilon = required_epsilon(args.target_error, args.sampling, args.reports)
    if epsilon is None:
        print("No epsilon under 3.0 meets the target.")
    else:
        print(f"Minimum epsilon: {epsilon:.2f}")
