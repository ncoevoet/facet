import { afterEach, vi } from 'vitest';
import { I18N } from './app/core/i18n/keys';
import { leafletMock } from './testing/leaflet-mock';

// Register before ANY component imports shared/leaflet, including indirect
// imports from specs which do not explicitly exercise a map.
vi.doMock('leaflet', () => leafletMock);

// Sanity check that the i18n keys source module loads. This setup file is not
// part of the builder's spec bundle, so it cannot initialize the bundled copy of
// keys.ts that components read; that is why component `I18N` fields must be
// initialized with `i18nKeys()` (see the header comment in keys.ts /
// gen-i18n-keys.mjs), never from a bare imported binding.
if (!I18N) {
  throw new Error('i18n keys module failed to initialize in the test setup');
}

// jsdom implements neither ResizeObserver nor IntersectionObserver, which the
// gallery / shared-view components (and Leaflet, when the real module leaks into
// the map spec) construct at runtime. Provide no-op stubs so those code paths
// don't throw ReferenceError under CI.
class _NoopObserver {
  observe(): void {}
  unobserve(): void {}
  disconnect(): void {}
  takeRecords(): unknown[] {
    return [];
  }
}
for (const name of ['ResizeObserver', 'IntersectionObserver'] as const) {
  if (!(name in globalThis)) {
    Object.defineProperty(globalThis, name, {
      writable: true,
      configurable: true,
      value: _NoopObserver,
    });
  }
}

// The Angular Vitest builder runs with isolate: false, so every spec file a
// worker executes shares ONE jsdom window. A global one file leaves shadowed is
// silently inherited by whichever file the scheduler runs next, and the failure
// surfaces there, in an unrelated spec, on some runs only. Fail at the offending
// test instead. history.state is the one that bit: an
// Object.defineProperty(history, 'state', { value }) freezes it for good,
// because jsdom's replaceState() only updates the field behind the prototype
// getter -- drive it through history.replaceState() instead.
afterEach(() => {
  if (Object.prototype.hasOwnProperty.call(history, 'state')) {
    // Drop the shadow before failing, so the blame stays on this test instead
    // of cascading onto every later test the worker runs.
    Reflect.deleteProperty(history, 'state');
    throw new Error(
      'history.state was shadowed with Object.defineProperty and left behind; ' +
        'use history.replaceState(...) -- the jsdom window is shared across spec files',
    );
  }
});

// jsdom does not implement window.matchMedia
// A plain function, NOT a vi.fn(): vitest's restoreAllMocks/resetAllMocks
// (called from other spec files' afterEach) would strip a vi.fn's
// implementation, leaving every later App in this shared worker with a
// matchMedia that returns undefined.
Object.defineProperty(window, 'matchMedia', {
  writable: true,
  value: (query: string) => ({
    matches: false,
    media: query,
    onchange: null,
    addListener() {},
    removeListener() {},
    addEventListener() {},
    removeEventListener() {},
    dispatchEvent: () => false,
  }),
});
