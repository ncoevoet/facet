import { signal, Signal } from '@angular/core';

/** Tailwind's `md`, the width at which this app calls itself desktop. */
const DEFAULT_BREAKPOINT_PX = 768;

export function useDesktopSignal(
  options?: { onChange?: (matches: boolean) => void; breakpointPx?: number },
): { isDesktop: Signal<boolean>; setup: () => void; cleanup: () => void } {
  const isDesktop = signal(false);
  let mql: MediaQueryList | null = null;
  let handler: ((e: MediaQueryListEvent) => void) | null = null;

  return {
    isDesktop: isDesktop.asReadonly(),
    setup() {
      mql = window.matchMedia(`(min-width: ${options?.breakpointPx ?? DEFAULT_BREAKPOINT_PX}px)`);
      isDesktop.set(mql.matches);
      handler = (e: MediaQueryListEvent) => {
        isDesktop.set(e.matches);
        options?.onChange?.(e.matches);
      };
      mql.addEventListener('change', handler);
    },
    cleanup() {
      if (mql && handler) {
        mql.removeEventListener('change', handler);
      }
    },
  };
}
