// Build-size gate used by CI. Exits non-zero if gzipped dist exceeds 30 KB.
const fs = require('fs')
const zlib = require('zlib')
const path = require('path')

const TARGET = path.join(__dirname, '..', 'client', 'dist', 'ldp.min.js')

if (!fs.existsSync(TARGET)) {
  console.error(`Missing bundle at ${TARGET}. Did you run the client build?`)
  process.exit(2)
}

const buf = fs.readFileSync(TARGET)
const gz = zlib.gzipSync(buf, { level: zlib.constants.Z_BEST_COMPRESSION })
const kb = gz.length / 1024
console.log(`gzipped size: ${kb.toFixed(2)} KB`)
if (kb > 30.0) {
  console.error('SDK exceeds 30 KB gzipped limit')
  process.exit(1)
}
