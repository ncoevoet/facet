import { afterEach, vi } from 'vitest';
import { I18N } from './app/core/i18n/keys';

// Force the leaf i18n keys module to initialize before any component module
// captures its `I18N` import. Under the Vitest unit-test builder, spec load
// order can otherwise evaluate a component module before keys.ts, snapshotting
// `I18N` as undefined and crashing any spec that renders an I18N-using template.
// This is a coarse, repo-wide backstop for that load-order risk; it does not
// replace initializing per-component `I18N` fields from `I18N_KEYS` rather than
// `I18N` (see the header comment in keys.ts / gen-i18n-keys.mjs) -- that fix
// addresses a distinct issue, an unrewritten self-shadowing reference under
// Vite's SSR transform, which this import alone cannot guard against.
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
Object.defineProperty(window, 'matchMedia', {
  writable: true,
  value: vi.fn().mockImplementation((query: string) => ({
    matches: false,
    media: query,
    onchange: null,
    addListener: vi.fn(),
    removeListener: vi.fn(),
    addEventListener: vi.fn(),
    removeEventListener: vi.fn(),
    dispatchEvent: vi.fn(),
  })),
});
