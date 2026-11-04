import { computed, inject } from '@angular/core';
import { Router } from '@angular/router';
import { trackPendingNavigation } from '../../shared/utils/navigation-settled';
import { pathOf } from '../../shared/utils/url-path';

/** Timeline children share one route boundary and cancellation policy. */
export function timelineRouteActivity(leaving?: () => void) {
  const router = inject(Router);
  const pending = trackPendingNavigation({ started: () => leaving?.() });
  return computed(() => !pending() && /^\/timeline(?:\/|$)/.test(pathOf(router.url)));
}
