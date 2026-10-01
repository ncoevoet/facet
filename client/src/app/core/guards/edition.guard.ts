import { inject } from '@angular/core';
import { CanActivateFn, Router } from '@angular/router';
import { AuthService } from '../services/auth.service';

/**
 * Pages that only issue edition-gated API calls. Runs after `authGuard`, so the
 * auth status is already loaded; a caller without edition (an open, read-only
 * install included) is sent to the gallery instead of a page of 403s.
 */
export const editionGuard: CanActivateFn = () => {
  const auth = inject(AuthService);
  return auth.isEdition() ? true : inject(Router).createUrlTree(['/']);
};
