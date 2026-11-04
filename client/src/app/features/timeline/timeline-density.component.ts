import { Component, ChangeDetectionStrategy, computed, effect, inject, input, signal, untracked } from '@angular/core';
import { ActivatedRoute, Router } from '@angular/router';
import { timelineRouteActivity } from './timeline-route-activity';
import { MatButtonModule } from '@angular/material/button';
import { ApiService } from '../../core/services/api.service';
import { AuthService } from '../../core/services/auth.service';
import { i18nKeys } from '../../core/i18n/keys';
import { TranslatePipe } from '../../shared/pipes/translate.pipe';
import { CaptureDatePipe } from '../../shared/pipes/capture-date.pipe';
import { GalleryStore } from '../gallery/gallery.store';
import { TimelineFiltersService } from './timeline-filters.service';
import { densityBuckets, densityRange, type DensityBucket, type DensityResponse } from './timeline-density.util';

@Component({
  selector: 'app-timeline-density',
  standalone: true,
  imports: [MatButtonModule, TranslatePipe, CaptureDatePipe],
  changeDetection: ChangeDetectionStrategy.OnPush,
  host: { class: 'block min-w-0' },
  template: `
    <details [open]="open()" class="border-b border-[var(--mat-sys-outline-variant)] py-0" (toggle)="toggle($event)" (keydown.escape)="close($event)">
      <summary class="min-h-9 cursor-pointer py-2 text-sm">{{ I18N.timeline.density | translate }}</summary>
      @if (open()) {
        <div class="flex flex-wrap items-center justify-between gap-x-3 gap-y-1 text-sm">
          @if (year()) {
            <label class="flex min-h-11 items-center gap-2">{{ I18N.timeline.density_unit | translate }}
              <select data-density-unit class="min-h-11 rounded border border-[var(--mat-sys-outline)] bg-[var(--mat-sys-surface)] px-2" [value]="unit()" (change)="unit.set($any($event.target).value)">
                <option value="auto" [selected]="unit() === 'auto'">{{ (month() ? I18N.timeline.density_days : I18N.timeline.density_months) | translate }}</option>
                <option value="week" [selected]="unit() === 'week'">{{ I18N.timeline.density_weeks | translate }}</option>
              </select>
            </label>
          } @else { <span>{{ unitLabel() | translate }}</span> }
          <label class="flex min-h-11 items-center gap-2">
            <input type="checkbox" [checked]="logScale()" (change)="logScale.set(!logScale())" />
            {{ I18N.timeline.log_scale | translate }}
          </label>
        </div>
        @if (loading()) { <p role="status" class="text-sm">{{ I18N.ui.labels.loading | translate }}</p> }
        @else if (failed()) {
          <p role="alert" class="text-sm">{{ I18N.timeline.load_failed | translate }}</p>
          <button mat-button (click)="retry.update(value => value + 1)">{{ I18N.timeline.retry | translate }}</button>
        } @else {
          @for (period of [year() + '-' + month()]; track period) {
          <div class="flex gap-1 overflow-x-auto pb-2 motion-safe:animate-[facet-calendar-enter_180ms_ease-out]" role="group" [attr.aria-label]="I18N.timeline.density | translate" [attr.aria-describedby]="helpId">
            @for (bucket of rendered(); track bucket.key) {
              <button type="button" class="flex min-h-20 min-w-11 flex-1 flex-col items-center gap-1 rounded px-1 py-1 text-xs hover:bg-[var(--mat-sys-surface-container)] focus-visible:outline-2 focus-visible:outline-offset-[-2px] focus-visible:outline-[var(--mat-sys-primary)]"
                [attr.aria-label]="I18N.timeline.period_count | translate: { period: unit() === 'week' ? (bucket.from | captureDate) + ' – ' + (bucket.to | captureDate) : bucket.key, count: bucket.count }"
                [attr.aria-pressed]="bucket.selected" [class]="bucket.selected ? 'bg-[var(--mat-sys-surface-container-high)]' : ''"
                (click)="choose(bucket)">
                <span class="flex h-10 w-full items-end justify-center border-b border-[var(--mat-sys-outline-variant)]" aria-hidden="true">
                  <span class="block w-full max-w-12 bg-[var(--mat-sys-primary)]" [style.height.%]="bucket.height"></span>
                </span>
                <span class="tabular-nums">{{ bucket.label }}</span>
                <span class="tabular-nums text-[var(--mat-sys-on-surface-variant)]">{{ bucket.count }}</span>
              </button>
            } @empty { <p class="text-sm">{{ I18N.timeline.empty | translate }}</p> }
          </div>
          }
          <p [id]="helpId" class="sr-only">{{ I18N.timeline.density_keyboard | translate }}</p>
          <button mat-button [attr.aria-pressed]="selectingRange()" (click)="selectingRange.set(!selectingRange()); clearDraft()">{{ I18N.timeline.select_range | translate }}</button>
          @if (selectingRange() || month() || (year() && unit() === 'week')) {
          <div class="flex flex-wrap items-center gap-1" role="group" [attr.aria-label]="I18N.timeline.range_boundary | translate">
            <button mat-button [attr.aria-pressed]="boundary() === 'start'" (click)="selectingRange.set(true); boundary.set('start')">{{ I18N.timeline.range_start | translate }}</button>
            <button mat-button [attr.aria-pressed]="boundary() === 'end'" (click)="selectingRange.set(true); boundary.set('end')">{{ I18N.timeline.range_end | translate }}</button>
            @if (range(); as selected) {
              <span role="status" class="px-2 text-sm tabular-nums">{{ selected.from | captureDate }} – {{ selected.to | captureDate }}</span>
              <button mat-stroked-button [disabled]="!active()" (click)="applyRange()">{{ I18N.timeline.apply_range | translate }}</button>
              <button mat-button (click)="clearDraft()">{{ I18N.timeline.clear_range | translate }}</button>
              @if (single() && !month() && (!year() || unit() !== 'week')) {
                <button mat-button (click)="explore()">{{ I18N.timeline.explore_period | translate }}</button>
              }
            }
          </div>
          }
        }
      }
    </details>
  `,
})
export class TimelineDensityComponent {
  private static nextId = 0;
  protected readonly helpId = `timeline-density-${TimelineDensityComponent.nextId++}`;
  protected readonly I18N = i18nKeys();
  private readonly api = inject(ApiService);
  private readonly auth = inject(AuthService);
  private readonly store = inject(GalleryStore);
  private readonly filters = inject(TimelineFiltersService);
  private readonly router = inject(Router);
  readonly year = input('');
  readonly month = input('');
  protected readonly open = signal(inject(ActivatedRoute).snapshot.queryParamMap.get('density') === '1');
  protected readonly active = timelineRouteActivity();
  protected readonly logScale = signal(false);
  protected readonly selectingRange = signal(false);
  protected readonly unit = signal<'auto' | 'week'>('auto');
  protected readonly loading = signal(false);
  protected readonly failed = signal(false);
  protected readonly retry = signal(0);
  protected readonly boundary = signal<'start' | 'end'>('start');
  private readonly first = signal<DensityBucket | null>(null);
  private readonly last = signal<DensityBucket | null>(null);
  private readonly buckets = signal<DensityBucket[]>([]);
  private currentRead: (() => boolean) | null = null;
  protected readonly range = computed(() => {
    const first = this.first(); const last = this.last();
    return first ? densityRange(first, last ?? first) : null;
  });
  protected readonly single = computed(() => this.first()?.key === (this.last() ?? this.first())?.key);
  protected readonly unitLabel = computed(() => this.month() ? this.I18N.timeline.density_days : this.year() ? this.I18N.timeline.density_months : this.I18N.timeline.density_years);
  protected readonly rendered = computed(() => {
    const rows = this.buckets(); const log = this.logScale(); const range = this.range();
    const scale = (count: number) => log ? Math.log1p(count) : count;
    const max = Math.max(1, ...rows.map(row => scale(row.count)));
    return rows.map(row => ({ ...row, height: row.count ? Math.max(2, scale(row.count) / max * 100) : 0,
      selected: !!range && row.from <= range.to && row.to >= range.from }));
  });

  constructor() {
    effect(onCleanup => {
      const open = this.open(); const active = this.active(); const owner = this.auth.status(); const token = this.auth.token;
      const year = this.year(); const month = this.month(); const unit = this.unit(); const visibility = this.store.viewFilterParams();
      const from = this.filters.dateFrom(); const to = this.filters.dateTo();
      const photos = this.store.photos(); this.retry();
      untracked(() => { this.currentRead = null; this.buckets.set([]); this.clearDraft(); this.failed.set(false); this.loading.set(false); });
      if (!open || !active || !owner) return;
      const path = month || (unit === 'week' && year) ? '/timeline/dates' : year ? '/timeline/months' : '/timeline/years';
      const params = { ...visibility, ...(year ? { year: +year } : {}), ...(month ? { month: +month } : {}), date_from: from, date_to: to };
      this.loading.set(true);
      let valid = true;
      const current = () => valid && token === this.auth.token && owner === this.auth.status() && this.active() && this.open()
        && year === this.year() && month === this.month() && unit === this.unit() && photos === this.store.photos()
        && visibility === this.store.viewFilterParams() && from === this.filters.dateFrom() && to === this.filters.dateTo();
      this.currentRead = current;
      const request = this.api.get<DensityResponse>(path, params).subscribe({
        next: response => { if (current()) { this.buckets.set(densityBuckets(response, year, month, { unit, from, to })); this.loading.set(false); } },
        error: () => { if (current()) { this.failed.set(true); this.loading.set(false); } },
      });
      onCleanup(() => { valid = false; request.unsubscribe(); });
    });

  }

  protected toggle(event: Event): void { this.open.set((event.target as HTMLDetailsElement).open); }
  protected close(event: Event): void {
    const details = event.currentTarget as HTMLDetailsElement;
    if (event.defaultPrevented || !details.open) return;
    event.preventDefault(); event.stopPropagation(); details.open = false; this.open.set(false);
    details.querySelector<HTMLElement>('summary')?.focus({ preventScroll: true });
  }
  protected clearDraft(): void { this.first.set(null); this.last.set(null); this.boundary.set('start'); }
  protected choose(bucket: DensityBucket): void {
    if (!this.currentRead?.() || !this.buckets().some(row => row.key === bucket.key)) return;
    if (!this.selectingRange() && !this.month() && (!this.year() || this.unit() !== 'week')) {
      void this.router.navigate(this.year() ? ['/timeline', this.year(), String(+bucket.key.slice(5, 7))] : ['/timeline', bucket.key], { queryParams: { density: '1' } });
      return;
    }
    if (this.boundary() === 'start' || !this.first()) { this.first.set(bucket); this.last.set(null); this.boundary.set('end'); }
    else { this.last.set(bucket); this.boundary.set('start'); }
  }

  protected applyRange(): void {
    const range = this.range();
    if (!range || !this.currentRead?.() || this.failed() || this.loading()) return;
    this.filters.dateFrom.set(range.from); this.filters.dateTo.set(range.to);
  }

  protected explore(): void {
    const bucket = this.first();
    if (!bucket || !this.single() || !this.currentRead?.()) return;
    void this.router.navigate(this.year() ? ['/timeline', this.year(), String(+bucket.key.slice(5, 7))] : ['/timeline', bucket.key]);
  }
}
