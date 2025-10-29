export function getCrypto(): Crypto {
  if (typeof crypto === "undefined") {
    throw new Error("Web Crypto API is required for the SDK.");
  }
  if (!crypto.getRandomValues) {
    throw new Error("crypto.getRandomValues is not available.");
  }
  return crypto;
}

export function getRandomValuesHex(bytes: number): string {
  const buffer = new Uint8Array(bytes);
  getCrypto().getRandomValues(buffer);
  return Array.from(buffer, (n) => n.toString(16).padStart(2, "0")).join("");
}

export function getRandomFloat(): number {
  const array = new Uint32Array(1);
  getCrypto().getRandomValues(array);
  return array[0]! / 0xffffffff;
}

export function shouldSample(probability: number): boolean {
  if (probability >= 1) {
    return true;
  }
  if (probability <= 0) {
    return false;
  }
  return getRandomFloat() < probability;
}
