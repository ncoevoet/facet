import { inject } from '@angular/core';
import { CanActivateFn, Router } from '@angular/router';
import { AuthService } from '../services/auth.service';

/**
 * Pages that only issue edition-gated API calls: a caller without edition (an
 * open, read-only install included) is sent to the gallery instead of a page of
 * 403s.
 *
 * Angular runs every `canActivate` guard of a route concurrently, so this guard
 * cannot assume `authGuard` has loaded the status first: on a cold load or a
 * deep link the signal is still null. It therefore awaits the same shared
 * status load (`loadStatus`, one request however many guards ask) before
 * deciding.
 */
export const editionGuard: CanActivateFn = async () => {
  const auth = inject(AuthService);
  const router = inject(Router);
  try {
    await auth.loadStatus();
  } catch {
    return router.createUrlTree(['/']);
  }
  return auth.isEdition() ? true : router.createUrlTree(['/']);
};
