import { Directive, DestroyRef, computed, effect, inject, signal } from '@angular/core';
import { timelineRouteActivity } from './timeline-route-activity';
import { Subscription } from 'rxjs';
import { ApiService } from '../../core/services/api.service';
import { AuthService } from '../../core/services/auth.service';

/** Shared read lifecycle for the optional year/month/day calendar views. */
@Directive()
export abstract class TimelineCollectionReader {
  private readonly api = inject(ApiService);
  private readonly auth = inject(AuthService);
  private readonly active = timelineRouteActivity(() => this.cancelRead());
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
    inject(DestroyRef).onDestroy(() => this.cancelRead());
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
