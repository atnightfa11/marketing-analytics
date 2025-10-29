#!/usr/bin/env node
import fs from "node:fs";
import zlib from "node:zlib";

const [, , bundlePath] = process.argv;

if (!bundlePath) {
  console.error("Usage: node scripts/benchmark_sdk.js <dist/index.js>");
  process.exit(1);
}

const code = fs.readFileSync(bundlePath);
const gzipped = zlib.gzipSync(code);
const kb = gzipped.byteLength / 1024;

console.log(`Bundle gzipped size: ${kb.toFixed(2)} KB`);
if (kb > 30) {
  console.error("Client SDK exceeds 30 KB gzipped.");
  process.exit(1);
}
