#!/usr/bin/env python3
import argparse
import json
import math
import random
from collections import defaultdict

def adjusted_probability(epsilon: float, sampling_rate: float):
    p = math.exp(epsilon) / (1 + math.exp(epsilon))
    q = 1 - p
    baseline = 0.5
    return (
        sampling_rate * p + (1 - sampling_rate) * baseline,
        sampling_rate * q + (1 - sampling_rate) * baseline,
    )

def rr_bit(true_value: bool, epsilon: float, sampling_rate: float) -> int:
    p, q = adjusted_probability(epsilon, sampling_rate)
    probability = p if true_value else q
    return 1 if random.random() < probability else 0

def simulate(trials: int, epsilon: float, sampling_rate: float):
    successes = 0
    for _ in range(trials):
        successes += rr_bit(True, epsilon, sampling_rate)
    mean = successes / trials
    p, _ = adjusted_probability(epsilon, sampling_rate)
    return mean, p

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Validate randomized response estimator.")
    parser.add_argument("--trials", type=int, default=10000)
    parser.add_argument("--epsilon", type=float, default=0.5)
    parser.add_argument("--sampling", type=float, default=0.5)
    args = parser.parse_args()

    mean, theoretical = simulate(args.trials, args.epsilon, args.sampling)
    print(json.dumps({"empirical_mean": mean, "theoretical": theoretical}))
