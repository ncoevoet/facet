import { Directive, DestroyRef, effect, inject, input, signal } from '@angular/core';
import { NavigationCancel, NavigationEnd, NavigationError, NavigationStart, Router } from '@angular/router';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { Subscription } from 'rxjs';
import { ApiService } from '../../core/services/api.service';
import { AuthService } from '../../core/services/auth.service';
import type { Photo } from '../../shared/models/photo.model';

/** Lazy photo-panel reads share cancellation and account ownership. */
@Directive()
export abstract class PhotoPanelReader<T> {
  protected abstract readonly endpoint: string;
  readonly photo = input.required<Photo>();
  private readonly api = inject(ApiService);
  private readonly auth = inject(AuthService);
  private readonly router = inject(Router);
  private readonly destroyRef = inject(DestroyRef);
  protected readonly expanded = signal(false);
  protected readonly loading = signal(false);
  protected readonly failed = signal(false);
  protected readonly data = signal<T | null>(null);
  private request?: Subscription;
  private revision = 0;
  private navigating = false;

  constructor() {
    effect(() => { this.photo(); this.auth.status(); this.reset(); });
    this.router.events.pipe(takeUntilDestroyed(this.destroyRef)).subscribe(event => {
      if (event instanceof NavigationStart) { this.navigating = true; this.reset(); }
      if (event instanceof NavigationEnd || event instanceof NavigationCancel || event instanceof NavigationError) this.navigating = false;
    });
    this.destroyRef.onDestroy(() => this.reset());
  }

  protected toggle(event: Event): void {
    event.preventDefault();
    if (this.expanded()) this.reset();
    else if (!this.navigating && this.auth.status()) { this.expanded.set(true); this.load(); }
  }

  protected close(event: Event, trigger: HTMLElement): void {
    event.preventDefault(); event.stopPropagation(); this.reset(); trigger.focus();
  }

  protected load(): void {
    if (!this.expanded() || this.navigating || !this.auth.status()) return;
    this.request?.unsubscribe();
    const revision = ++this.revision;
    const photo = this.photo();
    const owner = this.auth.status();
    const token = this.auth.token;
    const current = () => !this.destroyRef.destroyed && revision === this.revision && this.expanded()
      && !this.navigating && this.photo() === photo && this.auth.status() === owner && this.auth.token === token;
    this.data.set(null); this.failed.set(false); this.loading.set(true);
    this.request = this.api.get<T>(this.endpoint, { path: photo.path }).subscribe({
      next: data => {
        if (current()) { this.data.set(data); this.loading.set(false); }
        else if (revision === this.revision) this.reset();
      },
      error: () => {
        if (current()) { this.failed.set(true); this.loading.set(false); }
        else if (revision === this.revision) this.reset();
      },
    });
  }

  private reset(): void {
    this.revision++; this.request?.unsubscribe(); this.request = undefined;
    this.expanded.set(false); this.loading.set(false); this.failed.set(false); this.data.set(null);
  }
}
