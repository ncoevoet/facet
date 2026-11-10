import { DestroyRef } from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { NavigationCancel, NavigationEnd, NavigationError, NavigationStart, Router } from '@angular/router';
import { defaultIfEmpty, filter, firstValueFrom, Subscription } from 'rxjs';
import { AuthService } from '../../core/services/auth.service';

/** Retains the opening owner across cancelled navigation, but never across a completed one. */
export class AlbumDialogContext {
  private readonly owner: ReturnType<AuthService['identity']>;
  private readonly url: string;
  private departed = false;
  private pendingId: number | null = null;
  private readonly navigation: Subscription;

  constructor(private readonly auth: AuthService, private readonly router: Router, private readonly destroyRef: DestroyRef,
              private readonly requireEdition = true) {
    this.owner = auth.identity();
    this.url = router.url;
    this.navigation = router.events.pipe(takeUntilDestroyed(destroyRef)).subscribe(event => {
      if (event instanceof NavigationStart) this.pendingId = event.id;
      if (event instanceof NavigationEnd) this.departed = true;
      if ((event instanceof NavigationEnd || event instanceof NavigationCancel || event instanceof NavigationError) && event.id === this.pendingId) this.pendingId = null;
    });
  }

  dispose(): void { this.navigation.unsubscribe(); }

  invalidate(): void { this.departed = true; }

  current(): boolean {
    return !this.destroyRef.destroyed && !this.departed && this.auth.identity() === this.owner
      && (!this.requireEdition || this.auth.isEdition()) && this.router.url === this.url;
  }

  canStart(): boolean { return this.current() && this.pendingId === null && !this.router.currentNavigation(); }

  async settled(): Promise<boolean> {
    while (this.current() && this.pendingId !== null) {
      const id = this.pendingId;
      await firstValueFrom(this.router.events.pipe(filter(event =>
        (event instanceof NavigationEnd || event instanceof NavigationCancel || event instanceof NavigationError) && event.id === id),
        takeUntilDestroyed(this.destroyRef), defaultIfEmpty(null)));
      await Promise.resolve();
    }
    return this.current();
  }
}
