import { Directive, DestroyRef, computed, effect, inject, input, signal, untracked } from '@angular/core';
import { Subscription } from 'rxjs';
import { ApiService } from '../../core/services/api.service';
import { AuthService } from '../../core/services/auth.service';
import type { Photo } from '../../shared/models/photo.model';
import { trackPendingNavigation } from '../../shared/utils/navigation-settled';

/** Lazy photo-panel reads share cancellation and account ownership. */
@Directive()
export abstract class PhotoPanelReader<T> {
  protected abstract readonly endpoint: string;
  readonly photo = input.required<Photo>();
  protected readonly api = inject(ApiService);
  protected readonly auth = inject(AuthService);
  protected readonly destroyRef = inject(DestroyRef);
  protected readonly expanded = signal(false);
  protected readonly loading = signal(false);
  protected readonly failed = signal(false);
  protected readonly data = signal<T | null>(null);
  private readonly path = computed(() => this.photo().path);
  protected request?: Subscription;
  protected revision = 0;
  private readonly navigationPending = trackPendingNavigation({ started: () => this.reset() });
  protected get navigating(): boolean { return this.navigationPending(); }

  constructor() {
    // Keyed on the confirmed session, not the status object a same-session revalidation replaces or briefly nulls.
    effect(() => { this.path(); this.auth.session(); this.reset(); });
    // The same photo as a new object is a confirmed edit of it: read again in place rather than collapse the panel.
    effect(() => { this.photo(); untracked(() => { if (this.expanded()) this.load(); }); });
    this.destroyRef.onDestroy(() => this.reset());
  }

  /** Follows the panel's own toggle; a read the page cannot make now closes the panel again. */
  protected setExpanded(open: boolean, panel?: { close(): void }): void {
    if (open === this.expanded()) return;
    if (!open) { this.reset(); return; }
    if (this.navigating || !this.auth.session()) { panel?.close(); return; }
    this.expanded.set(true); this.load();
  }

  protected close(event: Event, trigger: { focus(): void }): void {
    event.preventDefault(); event.stopPropagation(); this.reset(); trigger.focus();
  }

  protected load(): void {
    if (!this.expanded() || this.navigating || !this.auth.session()) return;
    this.request?.unsubscribe();
    const revision = ++this.revision;
    const photo = this.photo();
    const current = this.scope();
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

  protected scope(): () => boolean {
    const revision = this.revision, path = this.path(), owner = this.auth.session(), token = this.auth.token;
    return () => !this.destroyRef.destroyed && revision === this.revision && this.expanded()
      && !this.navigating && this.path() === path && this.auth.session() === owner && this.auth.token === token;
  }

  protected reset(): void {
    this.revision++; this.request?.unsubscribe(); this.request = undefined;
    this.expanded.set(false); this.loading.set(false); this.failed.set(false); this.data.set(null);
    this.onReset();
  }

  protected onReset(): void { /* Panels may clear mutation-specific state too. */ }
}
