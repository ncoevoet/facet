import { timelineRouteActivity } from './timeline-route-activity';
import { Component, DestroyRef, ElementRef, Injector, afterEveryRender, afterNextRender, computed, effect, inject, input, signal, untracked, ChangeDetectionStrategy } from '@angular/core';
import { Router, RouterLink } from '@angular/router';
import { Subscription } from 'rxjs';
import { MatButtonModule } from '@angular/material/button';
import { MatIconModule } from '@angular/material/icon';
import { ApiService } from '../../core/services/api.service';
import { AuthService, type AuthStatus } from '../../core/services/auth.service';
import { i18nKeys } from '../../core/i18n/keys';
import { TranslatePipe } from '../../shared/pipes/translate.pipe';
import { ThumbnailUrlPipe } from '../../shared/pipes/thumbnail-url.pipe';
import { CaptureDatePipe } from '../../shared/pipes/capture-date.pipe';
import { TimelineDayQueryPipe, TimelinePhotoLinkPipe } from './timeline-day-query.pipe';
import { TimelineFiltersService } from './timeline-filters.service';
import { GalleryStore } from '../gallery/gallery.store';
import { TimelineFeedCache, type TimelineGroup, type TimelinePage } from './timeline-feed-cache.service';
import type { Photo } from '../../shared/models/photo.model';
import { timelineWindow } from './timeline-density.util';

@Component({
  selector: 'app-timeline-feed',
  standalone: true,
  imports: [RouterLink, MatButtonModule, MatIconModule, TranslatePipe, ThumbnailUrlPipe, CaptureDatePipe, TimelineDayQueryPipe, TimelinePhotoLinkPipe],
  host: { class: 'block min-w-0' },
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    <div class="flex items-center justify-between gap-2 py-0">
      <label class="flex min-h-11 min-w-0 flex-1 items-center gap-2 text-sm">
        <mat-icon aria-hidden="true">calendar_month</mat-icon>
        <span class="sr-only">{{ I18N.timeline.jump_month | translate }}</span>
        <input type="month" class="w-full min-w-0 max-w-44 rounded border border-[var(--mat-sys-outline)] bg-[var(--mat-sys-surface)] px-2 py-1"
          [value]="selectedMonth()" (change)="jumpMonth($event)" />
      </label>
      <button mat-button (click)="toggleDirection()" [disabled]="!active()">
        <mat-icon>{{ filters.sortDirection() === 'older' ? 'arrow_downward' : 'arrow_upward' }}</mat-icon>
        {{ (filters.sortDirection() === 'older' ? I18N.timeline.newest_first : I18N.timeline.oldest_first) | translate }}
      </button>
    </div>
    @for (group of groups(); track group.date) {
      <section class="mb-6" [attr.aria-label]="group.date">
        <header class="flex min-h-11 flex-wrap items-baseline justify-between gap-x-3 gap-y-1 py-0">
          <h2 class="m-0 text-base font-semibold tabular-nums">{{ group.date | captureDate }}</h2>
          <a mat-button routerLink="/" [queryParams]="group.date | timelineDayQuery:visibility()">
            {{ I18N.timeline.view_day | translate: { count: group.count } }}
            <mat-icon iconPositionEnd>chevron_right</mat-icon>
          </a>
        </header>
        <div class="grid grid-cols-3 gap-1 sm:grid-cols-4 xl:grid-cols-6">
          @for (photo of group.photos; track photo.path) {
            <a [href]="photo.path | timelinePhotoLink" (click)="openPhoto($event, photo)"
              class="relative block aspect-square min-w-0 overflow-hidden bg-[var(--mat-sys-surface-container)] focus-visible:z-10 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--mat-sys-primary)]"
              [attr.aria-label]="photo.filename">
              <img [src]="photo.path | thumbnailUrl:320:photo.preview_revision" alt="" loading="lazy" decoding="async" class="h-full w-full object-cover" />
            </a>
          }
        </div>
        @if (group.count > group.photos.length) {
          <p class="mb-0 mt-2 text-xs text-[var(--mat-sys-on-surface-variant)]">
            {{ I18N.timeline.preview_count | translate: { shown: group.photos.length, total: group.count } }}
          </p>
        }
      </section>
    }
    <div class="flex min-h-16 flex-wrap items-center justify-center gap-2 pb-4" aria-live="polite">
      @if (error()) { <p role="alert">{{ I18N.timeline.load_failed | translate }}</p> }
      @if (loading() && !manualLoading()) { <span role="status">{{ I18N.ui.labels.loading | translate }}</span> }
      @else if (!loading() && !error() && groups().length === 0) { <p>{{ I18N.timeline.empty | translate }}</p> }
      @if (error() || manualLoading() || (hasMore() && groups().length < 128)) {
        <button mat-stroked-button data-timeline-load-more [attr.aria-disabled]="loading()" (click)="loadMore()">
          {{ (loading() ? I18N.ui.labels.loading : error() ? I18N.timeline.retry : I18N.timeline.more_days) | translate }}
        </button>
      } @else if (!loading() && hasMore()) {
          <button mat-stroked-button data-timeline-continue (click)="continueWindow()">{{ I18N.timeline.continue_dates | translate }}</button>
      }
    </div>
  `,
})
export class TimelineFeedComponent {
  protected readonly I18N = i18nKeys();
  protected readonly filters = inject(TimelineFiltersService);
  private readonly store = inject(GalleryStore);
  private readonly api = inject(ApiService);
  private readonly auth = inject(AuthService);
  private readonly cache = inject(TimelineFeedCache);
  private readonly router = inject(Router);
  private readonly host = inject<ElementRef<HTMLElement>>(ElementRef);
  private readonly injector = inject(Injector);
  readonly year = input('');
  readonly month = input('');
  protected readonly selectedMonth = computed(() => this.year() && this.month() ? `${this.year()}-${this.month().padStart(2, '0')}` : '');
  protected readonly active = timelineRouteActivity(() => { this.remember(); this.cancel(); });
  protected readonly groups = signal<TimelineGroup[]>([]);
  protected readonly loading = signal(false);
  protected readonly manualLoading = signal(false);
  protected readonly error = signal(false);
  protected readonly hasMore = signal(false);
  protected readonly visibility = computed(() => this.store.viewFilterParams());
  private readonly nextCursor = signal<string | null>(null);
  private request: Subscription | null = null;
  private generation = 0;
  private context: { scope: string; params: Record<string, string | number>; owner: AuthStatus; token: string | null; rows: Photo[]; membershipRevision: number } | null = null;
  private scrollOwner: HTMLElement | null = null;
  private restoreScroll: number | null = null;

  private readonly params = computed(() => {
    const { from, to } = timelineWindow(this.year(), this.month(), this.filters.dateFrom(), this.filters.dateTo());
    return { ...this.visibility(), date_from: from, date_to: to, direction: this.filters.sortDirection(),
      limit: 8, photos_per_group: 8, sort_by: 'date_taken', granularity: 'day' };
  });

  constructor() {
    effect(onCleanup => {
      const params = this.params(); const owner = this.auth.status(); const active = this.active(); const rows = this.cache.rows(); const membershipRevision = this.cache.membershipRevision();
      untracked(() => {
      this.cancel(); this.context = null; this.groups.set([]); this.hasMore.set(false); this.error.set(false);
      if (!owner || !active) return;
      this.context = { params, owner, rows, membershipRevision, token: this.auth.token, scope: JSON.stringify(params) };
      const cached = this.cache.read(this.context.scope);
      this.groups.set(cached?.groups ?? []); this.hasMore.set(cached?.has_more ?? false);
      this.nextCursor.set(cached?.next_cursor ?? null); this.restoreScroll = cached?.scrollTop ?? 0;
      if (!cached && this.scrollOwner) this.scrollOwner.scrollTop = 0;
      if (!cached) this.loadMore();
      });
      onCleanup(() => this.cancel());
    });
    afterNextRender(() => {
      this.scrollOwner = this.host.nativeElement.closest('app-timeline');
      if (this.scrollOwner) {
        this.scrollOwner.scrollTop = this.restoreScroll ?? 0;
        this.restoreScroll = null;
        this.scrollOwner.addEventListener('scroll', this.remember, { passive: true });
      }
    });
    afterEveryRender({ write: () => {
      if (this.scrollOwner && this.restoreScroll !== null) {
        this.scrollOwner.scrollTop = this.restoreScroll;
        this.restoreScroll = null;
      }
    } });
    inject(DestroyRef).onDestroy(() => {
      this.cancel(); this.scrollOwner?.removeEventListener('scroll', this.remember);
    });
  }

  private cancel(): void { this.generation++; this.request?.unsubscribe(); this.request = null; this.loading.set(false); this.manualLoading.set(false); }

  private current(context: NonNullable<TimelineFeedComponent['context']>, generation: number): boolean {
    return generation === this.generation && this.active() && context === this.context
      && context.owner === this.auth.status() && context.token === this.auth.token && context.rows === this.cache.rows()
      && context.membershipRevision === this.cache.membershipRevision();
  }

  protected openPhoto(event: MouseEvent, photo: Photo): void {
    if (event.button !== 0 || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;
    event.preventDefault();
    if (!this.context || !this.current(this.context, this.generation)) return;
    this.remember(); this.cache.capturePhotos(this.groups());
    void this.router.navigate(['/photo'], { queryParams: { path: photo.path }, state: { photo, photoOrigin: 'timeline' } });
  }

  private readonly remember = (): void => {
    const context = this.context;
    if (!context || this.error() || this.loading() || !this.current(context, this.generation)) return;
    this.cache.save({ ...context, groups: this.groups(), next_cursor: this.nextCursor(), has_more: this.hasMore(),
      scrollTop: this.scrollOwner?.scrollTop ?? 0 });
  };

  protected loadMore(): void {
    const context = this.context;
    if (!context || this.loading() || !this.current(context, this.generation)) return;
    const button = this.host.nativeElement.querySelector<HTMLButtonElement>('[data-timeline-load-more]');
    const restoreFocus = !!button && this.host.nativeElement.ownerDocument.activeElement === button;
    this.manualLoading.set(!!button);
    const generation = ++this.generation;
    this.loading.set(true); this.error.set(false);
    this.request = this.api.get<TimelinePage>('/timeline', { ...context.params, cursor: this.nextCursor() ?? '' }).subscribe({
      next: page => {
        if (!this.current(context, generation)) return;
        const seen = new Set(this.groups().map(group => group.date));
        this.groups.update(groups => [...groups, ...page.groups.filter(group => !seen.has(group.date))]);
        this.nextCursor.set(page.next_cursor); this.hasMore.set(page.has_more && !!page.next_cursor);
        this.loading.set(false); this.manualLoading.set(false); this.remember();
        if (restoreFocus && this.host.nativeElement.ownerDocument.activeElement === button && (!this.hasMore() || this.groups().length >= 128)) {
          afterNextRender(() => {
            const doc = this.host.nativeElement.ownerDocument;
            if (this.current(context, generation) && (doc.activeElement === doc.body || doc.activeElement === button)) {
              this.host.nativeElement.querySelector<HTMLElement>('[data-timeline-continue], section:last-of-type .grid a[href]')?.focus();
            }
          }, { injector: this.injector });
        }
      },
      error: () => { if (this.current(context, generation)) { this.loading.set(false); this.manualLoading.set(false); this.error.set(true); } },
    });
  }

  protected jumpMonth(event: Event): void {
    const value = (event.target as HTMLInputElement).value;
    if (this.active() && /^\d{4}-(0[1-9]|1[0-2])$/.test(value)) void this.router.navigate(['/timeline', value.slice(0, 4), String(+value.slice(5))]);
  }

  protected toggleDirection(): void {
    if (this.active()) this.filters.sortDirection.update(value => value === 'older' ? 'newer' : 'older');
  }

  protected continueWindow(): void {
    const cursor = this.nextCursor();
    if (!cursor || !this.active()) return;
    const date = new Date(`${cursor}T12:00:00Z`);
    date.setUTCDate(date.getUTCDate() + (this.filters.sortDirection() === 'older' ? -1 : 1));
    const value = date.toISOString().slice(0, 10);
    if (this.filters.sortDirection() === 'older') this.filters.dateTo.set(value);
    else this.filters.dateFrom.set(value);
    if (this.scrollOwner) this.scrollOwner.scrollTop = 0;
  }
}
