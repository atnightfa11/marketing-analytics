// Boolean Randomized Response utilities for Local DP
// Uses crypto.getRandomValues for all randomness

// p = exp(eps) / (1 + exp(eps))
// q = 1 - p
export function probTrue(eps: number): number {
    const e = Math.exp(eps)
    return e / (1 + e)
  }
  
  // Adjust RR when client-side sampling s in [0,1] is used
  // Returns effective p', q' to keep server-side estimator unbiased
  export function adjustedP(eps: number, s: number): { p: number; q: number } {
    const p = probTrue(eps)
    const q = 1 - p
    const sClamped = Math.max(0, Math.min(1, s))
    // If a report is dropped with prob 1-s, the server must decode with
    // the mixture that includes "missing as random" only via counts n
    // We keep the RR channel the same and let the server pass sampling_rate along
    // For client code, we just return p and q and ship s separately
    return { p, q }
  }
  
  // Cryptographically secure coin flip that returns true with probability p
  export function flip(p: number): boolean {
    if (p <= 0) return false
    if (p >= 1) return true
    const u32 = new Uint32Array(1)
    crypto.getRandomValues(u32)
    const x = u32[0] / 2 ** 32
    return x < p
  }
  
  // RR over a bit t in {0,1}
  export function rrBit(t: 0 | 1, eps: number): 0 | 1 {
    const p = probTrue(eps)
    const q = 1 - p
    if (t === 1) return flip(p) ? 1 : 0
    return flip(q) ? 1 : 0
  }
  