import { trackPendingNavigation } from '../../shared/utils/navigation-settled';
import { DestroyRef, effect, inject, signal } from '@angular/core';
import { NavigationEnd, Router } from '@angular/router';
import { AuthService } from '../../core/services/auth.service';
import { StalenessGuardFactory } from '../../core/services/staleness-guard.service';
import { isGalleryCollectionUrl } from '../../shared/utils/url-path';

/** A filter editor may resume after cancelled navigation, but never under a stale session. */
export function createGalleryFilterContext(callbacks: { authChanged?: () => void; navigationStarted?: () => void } = {}) {
  const auth = inject(AuthService);
  const router = inject(Router);
  const guards = inject(StalenessGuardFactory);
  const destroyRef = inject(DestroyRef);
  let session = { owner: auth.identity(), status: auth.status(), token: auth.token };
  let context = newContext();
  const path = signal(router.url.split('?')[0]);


  function newContext() {
    const token = auth.token;
    return guards.create(destroyRef, { requireEdition: false, track: 'status', valid: () => auth.token === token });
  }

  function refreshContext(authChanged = false): void {
    if (!authChanged && (session.owner !== auth.identity() || session.status !== auth.status() || session.token !== auth.token)) return;
    context.dispose();
    session = { owner: auth.identity(), status: auth.status(), token: auth.token };
    context = newContext();
  }

  effect(() => {
    auth.identity(); auth.status();
    callbacks.authChanged?.();
    refreshContext(true);
  });
  const pending = trackPendingNavigation({
    started: () => callbacks.navigationStarted?.(),
    settled: event => {
      path.set((event instanceof NavigationEnd ? event.urlAfterRedirects : router.url).split('?')[0]);
      refreshContext();
    },
  });

  return {
    pending,
    current: () => !pending() && isGalleryCollectionUrl(path()) && context.current(),
  };
}
