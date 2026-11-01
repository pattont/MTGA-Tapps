import { fileURLToPath } from 'node:url';
import { defineConfig } from 'vitest/config';
import type { Plugin } from 'vite';
import react from '@vitejs/plugin-react';

/**
 * mana-font's stylesheet declares its icon font in four legacy formats (eot,
 * woff, ttf, svg) and never mentions the woff2 the package also ships, so
 * the browser fetched a 408 KB woff and the build carried 3.5 MB of fonts
 * nothing used. This rewrites that one @font-face to the woff2 alone and
 * drops the unused MPlantin face before Vite resolves the urls, so only the
 * 187 KB woff2 is emitted. The icon classes are untouched.
 */
export function manaFontWoff2(): Plugin {
  const face = /@font-face\{font-family:"Mana";[^}]*\}/;
  const plantin = /@font-face\{font-family:"MPlantin";[^}]*\}/;
  return {
    name: 'mana-font-woff2',
    enforce: 'pre',
    transform(code, id) {
      if (!id.replace(/\\/g, '/').includes('mana-font/css/')) return null;
      if (!face.test(code)) {
        this.warn('mana-font stylesheet changed shape; shipping its stock @font-face');
        return null;
      }
      return {
        code: code
          .replace(face, '@font-face{font-family:"Mana";src:url("../fonts/mana.woff2") format("woff2");font-weight:normal;font-style:normal}')
          .replace(plantin, ''),
        map: null,
      };
    },
  };
}

// https://vite.dev/config/
export default defineConfig({
  plugins: [manaFontWoff2(), react()],
  build: {
    rollupOptions: {
      // stream.html is the Stream Kit: OBS browser-source widgets, a separate
      // page with no app shell and a transparent background.
      input: {
        main: fileURLToPath(new URL('./index.html', import.meta.url)),
        stream: fileURLToPath(new URL('./stream.html', import.meta.url)),
      },
    },
  },
  server: {
    proxy: {
      '/api': 'http://127.0.0.1:8765',
    },
  },
  test: {
    environment: 'jsdom',
    setupFiles: './src/test/setup.ts',
    globals: true,
  },
});
