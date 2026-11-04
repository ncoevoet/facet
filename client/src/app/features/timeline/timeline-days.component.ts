import { Component, inject, signal, input, effect, output, ChangeDetectionStrategy } from '@angular/core';
import { MatIconModule } from '@angular/material/icon';
import { MatProgressSpinnerModule } from '@angular/material/progress-spinner';
import { TimelineCollectionReader } from './timeline-collection-reader';
import { ThumbnailUrlPipe } from '../../shared/pipes/thumbnail-url.pipe';
import { TranslatePipe } from '../../shared/pipes/translate.pipe';
import { TimelineFiltersService } from './timeline-filters.service';
import { GalleryStore, type ViewFilterParams } from '../gallery/gallery.store';
import { TimelineLoadFailureComponent } from './timeline-load-failure.component';

interface DateEntry {
  date: string;
  count: number;
  hero_photo_path: string | null;
  preview_revision?: string | null;
}

interface CalendarCell {
  date: string | null;
  day: number;
  count: number;
  hero_photo_path: string | null;
  preview_revision?: string | null;
}

@Component({
  selector: 'app-timeline-days',
  standalone: true,
  imports: [TimelineLoadFailureComponent, MatIconModule, MatProgressSpinnerModule, ThumbnailUrlPipe, TranslatePipe],
  changeDetection: ChangeDetectionStrategy.Eager,
  template: `
    @if (loading()) {
      <div class="flex justify-center py-16">
        <mat-spinner diameter="48" [attr.aria-label]="'ui.labels.loading' | translate" />
      </div>
    }

    @if (failed()) {
      <app-timeline-load-failure (retry)="retry.update(value => value + 1)" />
    }
    @if (!loading() && !failed()) {
      <!-- Day-of-week headers -->
      <div class="grid grid-cols-7 gap-2 mb-2">
        @for (d of weekDays; track d) {
          <div class="text-center text-sm font-medium opacity-50 py-1">{{ d }}</div>
        }
      </div>

      <!-- Calendar grid -->
      <div class="grid grid-cols-7 gap-2">
        @for (cell of calendarCells(); track cell.date ?? $index) {
          @if (cell.date) {
            <button
              class="relative rounded-xl overflow-hidden transition-shadow cursor-pointer aspect-square"
              [class]="cell.count > 0 ? 'hover:shadow-lg bg-[var(--mat-sys-surface-container)]' : 'opacity-40 bg-[var(--mat-sys-surface-container)] cursor-default'"
              (click)="cell.count > 0 && daySelected.emit(cell.date)">
              @if (cell.hero_photo_path) {
                <img [src]="cell.hero_photo_path | thumbnailUrl:320:cell.preview_revision"
                     alt=""
                     class="absolute inset-0 w-full h-full object-cover" loading="lazy" />
                <div class="absolute inset-0 bg-black/30"></div>
              }
              <div class="relative z-10 flex flex-col items-center justify-center h-full p-1"
                   [class.text-white]="!!cell.hero_photo_path">
                <span class="text-base font-semibold">{{ cell.day }}</span>
                @if (cell.count > 0) {
                  <span class="text-xs opacity-70">{{ cell.count }}</span>
                }
              </div>
            </button>
          } @else {
            <!-- Empty cell (padding for first week) -->
            <div class="aspect-square"></div>
          }
        }
      </div>
    }
  `,
})
export class TimelineDaysComponent extends TimelineCollectionReader {
  private readonly filters = inject(TimelineFiltersService);
  private readonly store = inject(GalleryStore);

  readonly year = input.required<string>();
  readonly month = input.required<string>();
  readonly daySelected = output<string>();

  protected readonly calendarCells = signal<CalendarCell[]>([]);

  // Generate Mon–Sun abbreviations from the browser locale (Monday-first)
  protected readonly weekDays = (() => {
    const fmt = new Intl.DateTimeFormat(undefined, { weekday: 'short' });
    // Jan 5 2026 is a Monday; generate 7 consecutive days
    return Array.from({ length: 7 }, (_, i) => fmt.format(new Date(2026, 0, 5 + i)));
  })();

  constructor() {
    super();
    effect(() => {
      const scope = this.readScope(); this.retry();
      const y = this.year();
      const m = this.month();
      const dateFrom = this.filters.dateFrom();
      const dateTo = this.filters.dateTo();
      const viewParams = this.store.viewFilterParams();
      this.calendarCells.set([]);
      if (y && m && scope) this.load(+y, +m, dateFrom, dateTo, viewParams);
    });
  }

  private load(
    year: number, month: number, dateFrom: string, dateTo: string, viewParams: ViewFilterParams,
  ): void {
    const params: Record<string, string | number> = { year, month, ...viewParams };
    if (dateFrom) params['date_from'] = dateFrom;
    if (dateTo) params['date_to'] = dateTo;
    this.loadData<{ dates: DateEntry[] }>('/timeline/dates', params, res => {

      // Build date lookup
      const dateMap = new Map<string, DateEntry>();
      for (const d of res.dates) {
        dateMap.set(d.date, d);
      }

      // Build calendar cells
      const firstDay = new Date(year, month - 1, 1);
      const daysInMonth = new Date(year, month, 0).getDate();
      // Monday=0, Sunday=6
      let startDow = firstDay.getDay() - 1;
      if (startDow < 0) startDow = 6;

      const cells: CalendarCell[] = [];
      // Padding cells for days before the 1st
      for (let i = 0; i < startDow; i++) {
        cells.push({ date: null, day: 0, count: 0, hero_photo_path: null });
      }

      for (let d = 1; d <= daysInMonth; d++) {
        const dateStr = `${year}-${String(month).padStart(2, '0')}-${String(d).padStart(2, '0')}`;
        const entry = dateMap.get(dateStr);
        cells.push({
          date: dateStr,
          day: d,
          count: entry?.count ?? 0,
          hero_photo_path: entry?.hero_photo_path ?? null,
          preview_revision: entry?.preview_revision,
        });
      }

      this.calendarCells.set(cells);
    });
  }
}
