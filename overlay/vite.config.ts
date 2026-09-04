import { defineConfig } from 'vite';
import preact from '@preact/preset-vite';

// The overlay page: one tiny bundle, no code splitting, no source maps in
// the artifact. Preact via the preset (React-style code compiles to Preact).
export default defineConfig({
  plugins: [preact()],
  clearScreen: false,
  build: {
    target: ['es2022', 'safari15'],
    minify: 'esbuild',
    sourcemap: false,
    cssCodeSplit: false,
    rollupOptions: { output: { manualChunks: undefined } },
  },
  test: {
    environment: 'jsdom',
    setupFiles: ['src/test-setup.ts'],
  },
});
