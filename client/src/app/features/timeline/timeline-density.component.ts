import { DOCUMENT } from '@angular/common';
import { Component, ChangeDetectionStrategy, ElementRef, computed, effect, inject, input, output, signal, untracked } from '@angular/core';
import { DecimalPipe } from '@angular/common';
import { Router } from '@angular/router';
import { timelineRouteActivity } from './timeline-route-activity';
import { MatButtonModule } from '@angular/material/button';
import { MatButtonToggleModule } from '@angular/material/button-toggle';
import { MatIconModule } from '@angular/material/icon';
import { MatTooltipModule } from '@angular/material/tooltip';
import { AuthService } from '../../core/services/auth.service';
import { i18nKeys } from '../../core/i18n/keys';
import { TranslatePipe } from '../../shared/pipes/translate.pipe';
import { CaptureDatePipe } from '../../shared/pipes/capture-date.pipe';
import { GalleryStore } from '../gallery/gallery.store';
import { TimelineFeedCache } from './timeline-feed-cache.service';
import { TimelineFiltersService } from './timeline-filters.service';
import { timelineDayQuery } from './timeline-day-query.pipe';
import { densityBuckets, densityRange, type DensityBucket, type DensityResponse } from './timeline-density.util';
import { TimelineLoadFailureComponent } from './timeline-load-failure.component';
import { TimelineReads } from './timeline-reads.service';

@Component({
  selector: 'app-timeline-density',
  standalone: true,
  imports: [TimelineLoadFailureComponent, MatButtonModule, MatButtonToggleModule, MatIconModule, MatTooltipModule, DecimalPipe, TranslatePipe, CaptureDatePipe],
  changeDetection: ChangeDetectionStrategy.OnPush,
  host: {
    class: 'block min-w-0',
    '(document:pointerup)': 'endDrag()',
    '(document:pointercancel)': 'endDrag()',
    '(document:keydown)': 'endPress()',
  },
  template: `
    @if (visible()) {
      <div class="flex items-start gap-2 border-b border-[var(--mat-sys-outline-variant)] pb-1">
        <div class="min-w-0 flex-1">
          @if (loading()) {
            <div class="h-23" aria-busy="true"><span class="sr-only">{{ I18N.ui.labels.loading | translate }}</span></div>
          } @else if (failed()) {
            <app-timeline-load-failure (retry)="retry.update(value => value + 1)" />
          } @else {
            <div class="flex min-h-23 select-none gap-0.5 overflow-x-auto" role="group" [attr.aria-label]="unitLabel() | translate" [attr.aria-describedby]="helpId"
              (keydown)="onKey($event)" (pointermove)="move($event)">
              @for (bucket of rendered(); track bucket.key) {
                @let period = unit() === 'week' ? (bucket.from | captureDate) + ' – ' + (bucket.to | captureDate) : bucket.key;
                <button type="button" [attr.data-density-key]="bucket.key" [tabindex]="bucket.key === tabKey() ? 0 : -1"
                  class="flex h-23 min-w-11 flex-1 flex-col justify-end gap-1 rounded px-0.5 py-1 hover:bg-[var(--mat-sys-surface-container)] focus-visible:outline-2 focus-visible:outline-offset-[-2px] focus-visible:outline-[var(--mat-sys-primary)]"
                  [class]="bucket.selected ? '!bg-[var(--mat-sys-secondary-container)]' : ''"
                  [matTooltip]="I18N.timeline.period_count | translate: { period: period, count: (bucket.count | number) ?? '' }"
                  [attr.aria-label]="I18N.timeline.period_count | translate: { period: period, count: bucket.count }"
                  [attr.aria-pressed]="bucket.selected"
                  (pointerdown)="startDrag($event, bucket)" (focus)="onFocus(bucket)" (click)="onClick($event, bucket)">
                  <span class="flex h-16 w-full items-end" aria-hidden="true">
                    <span class="block w-full rounded-t-sm bg-[var(--mat-sys-primary)]" [style.height.%]="bucket.height"></span>
                  </span>
                  <span class="block text-center text-xs tabular-nums">{{ bucket.label }}</span>
                </button>
              } @empty { <p class="text-sm">{{ I18N.timeline.empty | translate }}</p> }
            </div>
            <p [id]="helpId" class="sr-only">{{ I18N.timeline.density_keyboard | translate }}</p>
          }
          <p role="status" class="sr-only">
            @if (range(); as draft) { {{ I18N.timeline.range_draft | translate: { from: draft.from | captureDate, to: draft.to | captureDate } }} }
          </p>
        </div>
        <div class="flex shrink-0 items-center gap-1">
          @if (year()) {
            <mat-button-toggle-group hideSingleSelectionIndicator class="[--mat-button-toggle-height:32px]" [value]="unit()"
              [attr.aria-label]="I18N.timeline.density_unit | translate" (change)="unit.set($event.value)">
              <mat-button-toggle value="auto">{{ (month() ? I18N.timeline.density_days : I18N.timeline.density_months) | translate }}</mat-button-toggle>
              <mat-button-toggle value="week">{{ I18N.timeline.density_weeks | translate }}</mat-button-toggle>
            </mat-button-toggle-group>
          }
          <button mat-icon-button type="button" [attr.aria-pressed]="logScale()" [class]="logScale() ? '!bg-[var(--mat-sys-secondary-container)]' : ''"
            [matTooltip]="I18N.timeline.log_scale | translate" [attr.aria-label]="I18N.timeline.log_scale | translate"
            (click)="logScale.set(!logScale())">
            <mat-icon>show_chart</mat-icon>
          </button>
        </div>
      </div>
    }
  `,
})
export class TimelineDensityComponent {
  private static nextId = 0;
  protected readonly helpId = `timeline-density-${TimelineDensityComponent.nextId++}`;
  protected readonly I18N = i18nKeys();
  private readonly reads = inject(TimelineReads);
  private readonly auth = inject(AuthService);
  private readonly store = inject(GalleryStore);
  private readonly filters = inject(TimelineFiltersService);
  private readonly membership = inject(TimelineFeedCache);
  private readonly router = inject(Router);
  private readonly host = inject<ElementRef<HTMLElement>>(ElementRef);
  private readonly doc = inject(DOCUMENT);
  readonly year = input('');
  readonly month = input('');
  /** Hidden strips render nothing but keep reading, so the scope total stays current. */
  readonly visible = input(true);
  /** Sum of the current response's bucket counts; null while loading or failed. */
  readonly total = output<number | null>();
  protected readonly active = timelineRouteActivity();
  protected readonly logScale = signal(false);
  protected readonly unit = signal<'auto' | 'week'>('auto');
  protected readonly loading = signal(false);
  protected readonly failed = signal(false);
  protected readonly retry = signal(0);
  /** The highlighted draft: set by a drag or by Shift+Arrow, applied on release/Enter. */
  private readonly first = signal<DensityBucket | null>(null);
  private readonly last = signal<DensityBucket | null>(null);
  private readonly buckets = signal<DensityBucket[]>([]);
  private readonly focusKey = signal('');
  /** The range anchor: a keyboard-focused bar, a Shift+Arrow draft start or a first Shift+click. */
  private anchorKey = '';
  /** The anchor as it stood when the current pointer press began, before its focus could move it. */
  private pressAnchor: string | null = null;
  /** True from pointerdown until the click (or a key): focus in that window comes from the pointer. */
  private pressing = false;
  private dragStart: DensityBucket | null = null;
  private dragged = false;
  private suppressClick = false;
  private currentRead: (() => boolean) | null = null;
  protected readonly range = computed(() => {
    const first = this.first(); const last = this.last();
    return first ? densityRange(first, last ?? first) : null;
  });
  protected readonly tabKey = computed(() => {
    const rows = this.buckets(); const key = this.focusKey();
    return rows.some(row => row.key === key) ? key : rows[0]?.key ?? '';
  });
  protected readonly unitLabel = computed(() => {
    if (this.unit() === 'week' && this.year()) return this.I18N.timeline.density_weeks;
    if (this.month()) return this.I18N.timeline.density_days;
    return this.year() ? this.I18N.timeline.density_months : this.I18N.timeline.density_years;
  });
  protected readonly rendered = computed(() => {
    const rows = this.buckets(); const log = this.logScale(); const range = this.range();
    const scale = (count: number) => log ? Math.log1p(count) : count;
    const max = Math.max(1, ...rows.map(row => scale(row.count)));
    return rows.map(row => ({ ...row, height: row.count ? Math.max(2, scale(row.count) / max * 100) : 0,
      selected: !!range && row.from <= range.to && row.to >= range.from }));
  });

  constructor() {
    effect(onCleanup => {
      const active = this.active(); const owner = this.auth.status(); const token = this.auth.token;
      const year = this.year(); const month = this.month(); const unit = this.unit(); const visibility = this.store.viewFilterParams();
      const from = this.filters.dateFrom(); const to = this.filters.dateTo();
      const rows = this.membership.rows(); const revision = this.membership.membershipRevision(); this.retry();
      untracked(() => { this.currentRead = null; this.buckets.set([]); this.clearDraft(); this.anchorKey = ''; this.failed.set(false); this.loading.set(false); this.total.emit(null); });
      if (!active || !owner) return;
      const path = month || (unit === 'week' && year) ? '/timeline/dates' : year ? '/timeline/months' : '/timeline/years';
      const params = { ...visibility, ...(year ? { year: +year } : {}), ...(month ? { month: +month } : {}), date_from: from, date_to: to };
      this.loading.set(true);
      let valid = true;
      const current = () => valid && token === this.auth.token && owner === this.auth.status() && this.active()
        && year === this.year() && month === this.month() && unit === this.unit() && rows === this.membership.rows() && revision === this.membership.membershipRevision()
        && visibility === this.store.viewFilterParams() && from === this.filters.dateFrom() && to === this.filters.dateTo();
      this.currentRead = current;
      const request = this.reads.get<DensityResponse>(path, params).subscribe({
        next: response => {
          if (!current()) return;
          const built = densityBuckets(response, year, month, { unit, from, to });
          this.buckets.set(built); this.loading.set(false);
          this.total.emit(built.reduce((sum, row) => sum + row.count, 0));
        },
        error: () => { if (current()) { this.failed.set(true); this.loading.set(false); this.total.emit(null); } },
      });
      onCleanup(() => { valid = false; request.unsubscribe(); });
    });
  }

  private find(key: string | undefined): DensityBucket | null { return this.buckets().find(row => row.key === key) ?? null; }
  private clearDraft(): void { this.first.set(null); this.last.set(null); }

  /** Apply first..last as the capture-date range; refused when the read is stale. */
  private apply(first: DensityBucket, last: DensityBucket): void {
    if (!this.currentRead?.() || this.failed() || this.loading() || !this.find(first.key) || !this.find(last.key)) return;
    const range = densityRange(first, last);
    this.filters.dateFrom.set(range.from); this.filters.dateTo.set(range.to);
    this.clearDraft();
  }

  private drill(bucket: DensityBucket): void {
    if (this.year() && this.unit() === 'week') { this.apply(bucket, bucket); return; }
    if (this.month()) void this.router.navigate(['/'], { queryParams: timelineDayQuery(bucket.key, this.store.viewFilterParams()) });
    else void this.router.navigate(this.year() ? ['/timeline', this.year(), String(+bucket.key.slice(5, 7))] : ['/timeline', bucket.key]);
  }

  protected endPress(): void { this.pressing = false; }

  protected onFocus(bucket: DensityBucket): void {
    this.focusKey.set(bucket.key);
    if (!this.first() && !this.pressing) this.anchorKey = bucket.key;
  }

  protected onClick(event: MouseEvent, bucket: DensityBucket): void {
    const before = this.pressAnchor ?? this.anchorKey;
    this.pressAnchor = null; this.pressing = false;
    if (this.suppressClick) { this.suppressClick = false; return; }
    if (!this.currentRead?.() || !this.find(bucket.key)) return;
    const draft = this.first();
    if (draft && event.detail === 0 && !event.shiftKey) { this.apply(draft, this.last() ?? draft); return; }
    if (event.shiftKey) {
      const anchor = this.find(before);
      if (anchor) { this.anchorKey = ''; this.apply(anchor, bucket); } else { this.anchorKey = bucket.key; this.first.set(bucket); this.last.set(null); }
      return;
    }
    this.drill(bucket);
  }

  protected startDrag(event: PointerEvent, bucket: DensityBucket): void {
    this.suppressClick = false; this.dragged = false;
    this.pressAnchor = this.anchorKey; this.pressing = true;
    this.dragStart = event.pointerType === 'touch' || event.button !== 0 ? null : bucket;
  }

  protected move(event: PointerEvent): void {
    const start = this.dragStart;
    if (!start) return;
    if (!(event.buttons & 1)) { this.endDrag(); return; }
    const key = this.doc.elementFromPoint(event.clientX, event.clientY)?.closest<HTMLElement>('[data-density-key]')?.dataset['densityKey'];
    const bucket = this.find(key);
    if (!bucket) return;
    if (bucket.key !== start.key) this.dragged = true;
    if (this.dragged) { this.first.set(start); this.last.set(bucket); }
  }

  protected endDrag(): void {
    const first = this.first(); const last = this.last();
    const dragged = this.dragged;
    this.dragStart = null; this.dragged = false;
    if (!dragged) return;
    this.suppressClick = true;
    setTimeout(() => { this.suppressClick = false; });
    if (first && last && first.key !== last.key) this.apply(first, last);
    else this.clearDraft();
  }

  protected onKey(event: KeyboardEvent): void {
    const bucket = this.find((event.target as HTMLElement).closest<HTMLElement>('[data-density-key]')?.dataset['densityKey']);
    if (!bucket) return;
    if (event.key === 'ArrowLeft' || event.key === 'ArrowRight') {
      const rows = this.buckets();
      const next = rows[Math.min(rows.length - 1, Math.max(0, rows.indexOf(bucket) + (event.key === 'ArrowRight' ? 1 : -1)))];
      event.preventDefault();
      if (event.shiftKey) {
        const anchor = this.first() ?? bucket;
        this.anchorKey = anchor.key; this.first.set(anchor); this.last.set(next);
      } else this.clearDraft();
      this.host.nativeElement.querySelector<HTMLElement>(`[data-density-key="${next.key}"]`)?.focus();
    } else if (event.key === 'Enter') {
      const first = this.first();
      if (!first) return;
      event.preventDefault();
      this.apply(first, this.last() ?? first);
    } else if (event.key === 'Escape' && this.first()) {
      event.preventDefault(); event.stopPropagation(); this.clearDraft(); this.anchorKey = '';
    }
  }
}
