import { DestroyRef, effect, inject, signal } from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { NavigationCancel, NavigationCancellationCode, NavigationEnd, NavigationError, NavigationSkipped, NavigationStart, Router } from '@angular/router';
import { AuthService } from '../../core/services/auth.service';
import { StalenessGuardFactory } from '../../core/services/staleness-guard.service';

/** A filter editor may resume after cancelled navigation, but never under a stale session. */
export function createGalleryFilterContext(callbacks: { authChanged?: () => void; navigationStarted?: () => void } = {}) {
  const auth = inject(AuthService);
  const router = inject(Router);
  const guards = inject(StalenessGuardFactory);
  const destroyRef = inject(DestroyRef);
  let session = { owner: auth.identity(), status: auth.status(), token: auth.token };
  let context = newContext();
  const path = signal(router.url.split('?')[0]);
  const pending = signal(false);
  let navigationId = 0;

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
  router.events.pipe(takeUntilDestroyed()).subscribe(event => {
    if (event instanceof NavigationStart) {
      if (event.id < navigationId) return;
      navigationId = event.id; pending.set(true); callbacks.navigationStarted?.();
    } else if (event instanceof NavigationEnd || event instanceof NavigationSkipped || event instanceof NavigationError || event instanceof NavigationCancel) {
      if (event.id < navigationId) return;
      if (event instanceof NavigationCancel && (event.code === NavigationCancellationCode.Redirect || event.code === NavigationCancellationCode.SupersededByNewNavigation)) return;
      navigationId = event.id;
      path.set((event instanceof NavigationEnd ? event.urlAfterRedirects : router.url).split('?')[0]);
      pending.set(false); refreshContext();
    }
  });

  return {
    pending: pending.asReadonly(),
    current: () => !pending() && (path() === '/' || /^\/album\/\d+$/.test(path())) && context.current(),
  };
}
