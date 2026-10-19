import '@testing-library/jest-dom/vitest';

// Node 25+ defines its own global localStorage/sessionStorage, which is
// undefined unless Node runs with --localstorage-file. It shadows jsdom's
// storage, so put jsdom's back for tests on newer Node versions.
const dom = (globalThis as { jsdom?: { window: Window } }).jsdom;
if (dom) {
  for (const name of ['localStorage', 'sessionStorage'] as const) {
    if (!globalThis[name]) {
      Object.defineProperty(globalThis, name, {
        configurable: true,
        writable: true,
        value: dom.window[name],
      });
    }
  }
}
