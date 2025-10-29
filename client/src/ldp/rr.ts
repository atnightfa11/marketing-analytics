import { getRandomFloat } from "../utils/crypto";

export interface RandomizedResponseResult {
  bit: 0 | 1;
  p: number;
  q: number;
  variance: number;
}

export function probTrue(epsilon: number): { p: number; q: number } {
  const exp = Math.exp(epsilon);
  const p = exp / (1 + exp);
  const q = 1 - p;
  return { p, q };
}

export function adjustedProbability(epsilon: number, samplingRate: number): { p: number; q: number } {
  const { p, q } = probTrue(epsilon);
  const baseline = 0.5;
  const adjustedP = samplingRate * p + (1 - samplingRate) * baseline;
  const adjustedQ = samplingRate * q + (1 - samplingRate) * baseline;
  return { p: adjustedP, q: adjustedQ };
}

export function flip(probability: number): 0 | 1 {
  const draw = getRandomFloat();
  return draw < probability ? 1 : 0;
}

export function rrBit(
  value: boolean,
  epsilon: number,
  samplingRate: number
): RandomizedResponseResult {
  const { p, q } = adjustedProbability(epsilon, samplingRate);
  const probability = value ? p : q;
  const bit = flip(probability);
  const variance = probability * (1 - probability);
  return {
    bit: bit as 0 | 1,
    p,
    q,
    variance,
  };
}
