import { DestroyRef, inject, signal } from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { NavigationStart, Router } from '@angular/router';
import { isNavigationSettled } from '../../shared/utils/navigation-settled';
import { pathOf } from '../../shared/utils/url-path';

/** Timeline children share one route boundary and cancellation policy. */
export function timelineRouteActivity(leaving?: () => void) {
  const router = inject(Router);
  const active = signal(true);
  let id = 0;
  router.events.pipe(takeUntilDestroyed(inject(DestroyRef))).subscribe(event => {
    if (event instanceof NavigationStart && event.id >= id) {
      id = event.id; leaving?.(); active.set(false);
    } else if (isNavigationSettled(event) && event.id >= id) {
      id = event.id; active.set(/^\/timeline(?:\/|$)/.test(pathOf(router.url)));
    }
  });
  return active.asReadonly();
}
