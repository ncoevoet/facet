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

/**
 * The query a finger or stylus answers, and a mouse does not.
 *
 * Kept beside the width breakpoint because "is this a phone" is really two
 * questions — how much room the layout has, and what the user is pointing
 * with — and a gesture affordance only ever wants the second one: a narrow
 * desktop window is still driven by a mouse, where a swipe is unreachable.
 */
const COARSE_POINTER_QUERY = '(pointer: coarse)';

/** A signal tracking one media query, live for as long as `setup`/`cleanup` bracket it. */
function useMediaQuerySignal(
  query: string,
  onChange?: (matches: boolean) => void,
): { matches: Signal<boolean>; setup: () => void; cleanup: () => void } {
  const matches = signal(false);
  let mql: MediaQueryList | null = null;
  let handler: ((e: MediaQueryListEvent) => void) | null = null;

  return {
    matches: matches.asReadonly(),
    setup() {
      mql = window.matchMedia(query);
      matches.set(mql.matches);
      handler = (e: MediaQueryListEvent) => {
        matches.set(e.matches);
        onChange?.(e.matches);
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

export function useDesktopSignal(
  options?: { onChange?: (matches: boolean) => void; breakpointPx?: number },
): { isDesktop: Signal<boolean>; setup: () => void; cleanup: () => void } {
  const query = useMediaQuerySignal(
    `(min-width: ${options?.breakpointPx ?? DEFAULT_BREAKPOINT_PX}px)`,
    options?.onChange,
  );
  return { isDesktop: query.matches, setup: query.setup, cleanup: query.cleanup };
}

/** Whether the primary pointer is a finger or a stylus rather than a mouse. */
export function useCoarsePointerSignal(): {
  isCoarsePointer: Signal<boolean>;
  setup: () => void;
  cleanup: () => void;
} {
  const query = useMediaQuerySignal(COARSE_POINTER_QUERY);
  return { isCoarsePointer: query.matches, setup: query.setup, cleanup: query.cleanup };
}
