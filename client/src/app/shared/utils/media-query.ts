import { signal, Signal } from '@angular/core';

/** Tailwind's `md`, the width at which this app calls itself desktop. */
const DEFAULT_BREAKPOINT_PX = 768;

/**
 * Narrowest viewport that can spare a permanent ~320px details rail (Tailwind `xl`).
 *
 * Shared so the gallery's rail and the header menu that offers it agree: a menu
 * entry that switches to a mode the viewport cannot render is worse than no
 * entry at all.
 */
export const DETAILS_RAIL_MIN_WIDTH_PX = 1280;

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
