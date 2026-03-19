import { Component, inject, signal, input, effect, output } from '@angular/core';
import { DecimalPipe } from '@angular/common';
import { MatIconModule } from '@angular/material/icon';
import { MatProgressSpinnerModule } from '@angular/material/progress-spinner';
import { firstValueFrom } from 'rxjs';
import { ApiService } from '../../core/services/api.service';
import { TranslatePipe } from '../../shared/pipes/translate.pipe';
import { ThumbnailUrlPipe } from '../../shared/pipes/thumbnail-url.pipe';
import { TimelineDatePipe } from './timeline-date.pipe';
import { TimelineFiltersService } from './timeline-filters.service';

interface MonthSummary {
  month: string;
  count: number;
  hero_photo_path: string | null;
}

@Component({
  selector: 'app-timeline-months',
  standalone: true,
  imports: [DecimalPipe, MatIconModule, MatProgressSpinnerModule, TranslatePipe, ThumbnailUrlPipe, TimelineDatePipe],
  template: `
    @if (loading() && months().length === 0) {
      <div class="flex justify-center py-16">
        <mat-spinner diameter="48" />
      </div>
    }

    @if (!loading() && months().length === 0) {
      <div class="text-center py-16 opacity-60">
        <mat-icon class="!text-5xl !w-12 !h-12 mb-4">calendar_today</mat-icon>
        <p>{{ 'timeline.no_photos_month' | translate }}</p>
      </div>
    }

    <div class="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-5 xl:grid-cols-6 gap-4">
      @for (m of months(); track m.month) {
        <button
          class="group flex flex-col rounded-xl overflow-hidden bg-[var(--mat-sys-surface-container)] hover:shadow-lg transition-shadow cursor-pointer text-left"
          (click)="monthSelected.emit(m.month)">
          @if (m.hero_photo_path) {
            <div class="relative w-full aspect-[4/3] overflow-hidden">
              <img [src]="m.hero_photo_path | thumbnailUrl:320"
                   [alt]="m.month"
                   class="w-full h-full object-cover group-hover:scale-105 transition-transform duration-300" />
            </div>
          } @else {
            <div class="w-full aspect-[4/3] flex items-center justify-center bg-[var(--mat-sys-surface-container-high)]">
              <mat-icon class="!text-4xl !w-10 !h-10 opacity-30">calendar_today</mat-icon>
            </div>
          }
          <div class="p-3">
            <div class="text-lg font-semibold">{{ m.month | timelineDate }}</div>
            <div class="text-sm opacity-60">{{ m.count | number }} {{ 'timeline.photos_count' | translate }}</div>
          </div>
        </button>
      }
    </div>
  `,
})
export class TimelineMonthsComponent {
  private readonly api = inject(ApiService);
  private readonly filters = inject(TimelineFiltersService);

  readonly year = input.required<string>();
  readonly monthSelected = output<string>();

  protected readonly months = signal<MonthSummary[]>([]);
  protected readonly loading = signal(false);

  constructor() {
    effect(() => {
      const y = this.year();
      const dateFrom = this.filters.dateFrom();
      const dateTo = this.filters.dateTo();
      if (y) this.load(y, dateFrom, dateTo);
    });
  }

  private async load(year: string, dateFrom: string, dateTo: string): Promise<void> {
    this.loading.set(true);
    try {
      const params: Record<string, string | number> = { year: +year };
      if (dateFrom) params['date_from'] = dateFrom;
      if (dateTo) params['date_to'] = dateTo;
      const res = await firstValueFrom(
        this.api.get<{ months: MonthSummary[] }>('/timeline/months', params),
      );
      this.months.set(res.months);
    } finally {
      this.loading.set(false);
    }
  }

}
