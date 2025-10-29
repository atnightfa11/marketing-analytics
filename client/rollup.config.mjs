import replace from "@rollup/plugin-replace";
import resolve from "@rollup/plugin-node-resolve";
import commonjs from "@rollup/plugin-commonjs";
import typescript from "@rollup/plugin-typescript";
import terser from "@rollup/plugin-terser";
import fs from "node:fs";
import zlib from "node:zlib";

export default {
  input: "src/index.ts",
  output: [
    {
      file: "dist/index.js",
      format: "esm",
      sourcemap: true
    }
  ],
  treeshake: true,
  plugins: [
    resolve({
      browser: true,
      preferBuiltins: false
    }),
    commonjs(),
    typescript({
      tsconfig: "./tsconfig.json"
    }),
    replace({
      preventAssignment: true,
      "process.env.NODE_ENV": JSON.stringify("production")
    }),
    terser({
      format: {
        comments: false
      }
    }),
    {
      name: "bundle-size-reporter",
      writeBundle(options) {
        const file = options.file ?? "dist/index.js";
        const code = fs.readFileSync(file);
        const gzipped = zlib.gzipSync(code);
        const kb = gzipped.byteLength / 1024;
        if (kb > 30) {
          throw new Error(`SDK bundle exceeds 30KB gzipped (actual ${kb.toFixed(2)}KB)`);
        }
        // eslint-disable-next-line no-console
        console.log(`SDK gzipped size: ${kb.toFixed(2)}KB`);
      }
    }
  ]
};
