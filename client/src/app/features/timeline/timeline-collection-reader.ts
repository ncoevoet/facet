import { Directive, DestroyRef, computed, effect, inject, signal } from '@angular/core';
import { Router, NavigationStart, NavigationEnd, NavigationCancel, NavigationError } from '@angular/router';
import { Subscription } from 'rxjs';
import { ApiService } from '../../core/services/api.service';
import { AuthService } from '../../core/services/auth.service';

/** Shared read lifecycle for the optional year/month/day calendar views. */
@Directive()
export abstract class TimelineCollectionReader {
  private readonly api = inject(ApiService);
  private readonly auth = inject(AuthService);
  private readonly router = inject(Router);
  private readonly active = signal(true);
  protected readonly loading = signal(false);
  protected readonly failed = signal(false);
  protected readonly retry = signal(0);
  protected readonly readScope = computed(() => {
    const owner = this.auth.status();
    return owner && this.active() ? { owner, token: this.auth.token } : null;
  });
  private request: Subscription | null = null;
  private generation = 0;

  constructor() {
    effect(() => { if (!this.readScope()) this.cancelRead(); });
    const navigation = this.router.events.subscribe(event => {
      if (event instanceof NavigationStart) { this.active.set(false); this.cancelRead(); }
      else if (event instanceof NavigationEnd || event instanceof NavigationCancel || event instanceof NavigationError) this.active.set(/^\/timeline(?:\/|$)/.test(this.router.url.split('?')[0]));
    });
    inject(DestroyRef).onDestroy(() => { navigation.unsubscribe(); this.cancelRead(); });
  }

  protected cancelRead(): void {
    this.generation++; this.request?.unsubscribe(); this.request = null; this.loading.set(false);
  }

  protected loadData<T>(path: string, params: Record<string, string | number>, accept: (response: T) => void): void {
    this.cancelRead(); this.failed.set(false);
    const scope = this.readScope();
    if (!scope) return;
    const generation = this.generation;
    const current = () => generation === this.generation && this.active()
      && scope.owner === this.auth.status() && scope.token === this.auth.token;
    this.loading.set(true);
    this.request = this.api.get<T>(path, params).subscribe({
      next: response => { if (current()) { accept(response); this.loading.set(false); } },
      error: () => { if (current()) { this.failed.set(true); this.loading.set(false); } },
    });
  }
}
