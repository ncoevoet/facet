import { Directive, DestroyRef, ElementRef, Injector, afterNextRender, computed, effect, inject, signal } from '@angular/core';
import { timelineRouteActivity } from './timeline-route-activity';
import { Subscription } from 'rxjs';
import { ApiService } from '../../core/services/api.service';
import { AuthService } from '../../core/services/auth.service';
import { timelineReadContext } from './timeline-read-context';

/** Shared read lifecycle for the optional year/month/day calendar views. */
@Directive()
export abstract class TimelineCollectionReader {
  private readonly api = inject(ApiService);
  private readonly auth = inject(AuthService);
  private readonly host = inject<ElementRef<HTMLElement>>(ElementRef, { optional: true });
  private readonly injector = inject(Injector);
  private retryButton: HTMLElement | null = null;
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

  protected cancelRead(preserveRetry = false): void {
    this.generation++; this.request?.unsubscribe(); this.request = null; this.loading.set(false);
    if (!preserveRetry) this.retryButton = null;
  }

  protected retryRead(): void {
    if (this.loading()) return;
    const active = this.host?.nativeElement.ownerDocument.activeElement;
    this.retryButton = active instanceof HTMLElement && this.host?.nativeElement.contains(active) ? active : null;
    this.retry.update(value => value + 1);
  }

  protected loadData<T>(path: string, params: Record<string, string | number>, accept: (response: T) => void): void {
    this.cancelRead(true);
    if (!this.retryButton) this.failed.set(false);
    const scope = this.readScope();
    if (!scope) return;
    const generation = this.generation;
    const current = () => generation === this.generation && this.active()
      && scope.owner === this.auth.status() && scope.token === this.auth.token;
    this.loading.set(true);
    this.request = this.api.get<T>(path, params, timelineReadContext()).subscribe({
      next: response => { if (current()) {
        const button = this.retryButton; this.retryButton = null;
        const restore = !!button && button.ownerDocument.activeElement === button;
        accept(response); this.failed.set(false); this.loading.set(false);
        if (restore) afterNextRender(() => {
          const host = this.host?.nativeElement;
          if (host && current() && (host.ownerDocument.activeElement === host.ownerDocument.body || host.ownerDocument.activeElement === button)) {
            (host.querySelector<HTMLElement>('[data-timeline-result]:not([disabled])') ?? host.querySelector<HTMLElement>('[data-timeline-empty]'))?.focus();
          }
        }, { injector: this.injector });
      } },
      error: () => { if (current()) { this.retryButton = null; this.failed.set(true); this.loading.set(false); } },
    });
  }
}
