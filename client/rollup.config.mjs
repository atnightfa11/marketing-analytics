import { defineConfig } from 'rollup'
import typescript from '@rollup/plugin-typescript'
import replace from '@rollup/plugin-replace'
import terser from '@rollup/plugin-terser'

export default defineConfig({
  input: 'client/src/index.ts',
  output: {
    file: 'client/dist/ldp.min.js',
    format: 'esm',
    sourcemap: false
  },
  plugins: [
    replace({
      preventAssignment: true,
      'process.env.NODE_ENV': JSON.stringify('production')
    }),
    typescript({ tsconfig: 'client/tsconfig.json' }),
    terser()
  ],
  treeshake: true
})
