import { vi } from 'vitest';
import { I18N } from './app/core/i18n/keys';

// Force the leaf i18n keys module to initialize before any component module
// captures its `I18N` import. Under the Vitest unit-test builder, spec load
// order can otherwise evaluate a component module before keys.ts, snapshotting
// `I18N` as undefined and crashing any spec that renders an I18N-using template
// (e.g. photo-card / person-card). Referencing it here pins the init order.
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
