import { DestroyRef, inject, Injectable } from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { NavigationStart, Router } from '@angular/router';
import { AuthService } from './auth.service';

export interface StalenessOptions {
  /** Read-only commands still need account/navigation guards, without edition access. */
  requireEdition?: boolean;
  /** What identifies the owner: the user id (default) or the whole auth status object, which also
   *  changes when the same session is revalidated. */
  track?: 'identity' | 'status';
  /** Extra condition that must still hold, e.g. the photo shown when the launch began. */
  valid?: () => boolean;
  /** Called on every NavigationStart, once the guard has marked itself navigated. */
  onNavigate?: () => void;
}

export interface StalenessGuard {
  /** Same owner, required edit access, page and extra condition, and no navigation since. */
  session: () => boolean;
  /** `session()` and the owning injector is still alive. */
  current: () => boolean;
  /** Ends the navigation watch; also ended by the owner's destruction. */
  dispose: () => void;
}

/** Captures the owner, page and navigation state when a dialog launch (or a dialog) begins, so a
 *  late chunk load or server answer can tell whether it still belongs to the same context. */
@Injectable({ providedIn: 'root' })
export class StalenessGuardFactory {
  private readonly auth = inject(AuthService);
  private readonly router = inject(Router);

  create(destroyRef: DestroyRef, options: StalenessOptions = {}): StalenessGuard {
    const read = () => options.track === 'status' ? this.auth.status() : this.auth.identity();
    const owner = read();
    const url = this.router.url;
    let navigated = false;
    const navigation = this.router.events.pipe(takeUntilDestroyed(destroyRef)).subscribe(event => {
      if (event instanceof NavigationStart) { navigated = true; options.onNavigate?.(); }
    });
    const session = () => !navigated && read() === owner && (options.requireEdition === false || this.auth.isEdition()) && this.router.url === url && (options.valid?.() ?? true);
    return { session, current: () => !destroyRef.destroyed && session(), dispose: () => navigation.unsubscribe() };
  }
}
