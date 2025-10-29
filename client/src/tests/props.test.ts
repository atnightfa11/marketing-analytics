import { webcrypto } from "crypto";
import { adjustedProbability } from "../ldp/rr";

Object.defineProperty(globalThis, "crypto", {
  value: webcrypto,
  configurable: true,
});

describe("RR property checks", () => {
  const epsilons = [0.2, 0.5, 1.0];
  const samplings = [0.3, 0.6, 1.0];

  test.each(epsilons)("p > q for epsilon %p", (epsilon) => {
    const { p, q } = adjustedProbability(epsilon, 1.0);
    expect(p).toBeGreaterThan(q);
  });

  test.each(samplings)("sampling shrinks towards 0.5 (%p)", (s) => {
    const epsilon = 0.8;
    const { p, q } = adjustedProbability(epsilon, s);
    expect(p).toBeGreaterThan(q);
    expect(p).toBeLessThanOrEqual(1);
    expect(q).toBeGreaterThanOrEqual(0);
    if (s < 1) {
      expect(p).toBeLessThan(1);
      expect(q).toBeGreaterThan(0);
    }
  });
});
