import { webcrypto } from "crypto";
import { rrBit, probTrue } from "../ldp/rr";

Object.defineProperty(globalThis, "crypto", {
  value: webcrypto,
  configurable: true,
});

describe("Randomized response sanity checks", () => {
  test("rrBit approximates theoretical expectation", () => {
    const epsilon = 0.7;
    const sampling = 0.8;
    const { p } = probTrue(epsilon);
    const trials = 5000;
    let sum = 0;
    for (let i = 0; i < trials; i += 1) {
      sum += rrBit(true, epsilon, sampling).bit;
    }
    const empiricalMean = sum / trials;
    expect(empiricalMean).toBeGreaterThan(p - 0.05);
    expect(empiricalMean).toBeLessThan(p + 0.05);
  });

  test("variance stays within expected bounds", () => {
    const epsilon = 0.3;
    const sampling = 0.6;
    const runs = 2000;
    const values: number[] = [];
    for (let i = 0; i < runs; i += 1) {
      values.push(rrBit(false, epsilon, sampling).bit);
    }
    const mean = values.reduce((a, b) => a + b, 0) / values.length;
    const variance = values.reduce((acc, val) => acc + (val - mean) ** 2, 0) / values.length;
    expect(variance).toBeLessThan(0.3);
    expect(variance).toBeGreaterThan(0.1);
  });
});
