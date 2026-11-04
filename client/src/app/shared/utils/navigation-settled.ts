import { DestroyRef, inject, signal } from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { Event, NavigationCancel, NavigationCancellationCode, NavigationEnd, NavigationError, NavigationSkipped, NavigationStart, Router } from '@angular/router';

/** Redirects and superseded requests transfer control to another navigation. */
export function isNavigationSettled(event: Event): event is NavigationEnd | NavigationError | NavigationSkipped | NavigationCancel {
  return event instanceof NavigationEnd || event instanceof NavigationError || event instanceof NavigationSkipped
    || event instanceof NavigationCancel && event.code !== NavigationCancellationCode.Redirect
      && event.code !== NavigationCancellationCode.SupersededByNewNavigation;
}

/** One navigation owner; older completions cannot unlock a newer request. */
export function trackPendingNavigation(callbacks: {
  /** Some panels keep working through their own query-only navigation. */
  blocks?: (event: NavigationStart) => boolean;
  started?: (event: NavigationStart) => void;
  settled?: (event: NavigationEnd | NavigationError | NavigationSkipped | NavigationCancel) => void;
} = {}) {
  const router = inject(Router);
  const current = router.currentNavigation?.();
  const pending = signal(!!current);
  let id = current?.id ?? 0;
  router.events.pipe(takeUntilDestroyed(inject(DestroyRef))).subscribe(event => {
    if (event instanceof NavigationStart && event.id >= id) {
      id = event.id; pending.set(callbacks.blocks?.(event) ?? true); callbacks.started?.(event);
    } else if (isNavigationSettled(event) && event.id >= id) {
      id = event.id; pending.set(false); callbacks.settled?.(event);
    }
  });
  return pending.asReadonly();
}
