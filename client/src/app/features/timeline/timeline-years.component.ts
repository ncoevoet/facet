import { Component, inject, signal, effect, output } from '@angular/core';
import { DecimalPipe } from '@angular/common';
import { MatIconModule } from '@angular/material/icon';
import { MatProgressSpinnerModule } from '@angular/material/progress-spinner';
import { firstValueFrom } from 'rxjs';
import { ApiService } from '../../core/services/api.service';
import { TranslatePipe } from '../../shared/pipes/translate.pipe';
import { ThumbnailUrlPipe } from '../../shared/pipes/thumbnail-url.pipe';
import { TimelineFiltersService } from './timeline-filters.service';

interface YearSummary {
  year: string;
  count: number;
  hero_photo_path: string | null;
}

@Component({
  selector: 'app-timeline-years',
  standalone: true,
  imports: [DecimalPipe, MatIconModule, MatProgressSpinnerModule, TranslatePipe, ThumbnailUrlPipe],
  template: `
    @if (loading() && years().length === 0) {
      <div class="flex justify-center py-16">
        <mat-spinner diameter="48" />
      </div>
    }

    @if (!loading() && years().length === 0) {
      <div class="text-center py-16 opacity-60">
        <mat-icon class="!text-5xl !w-12 !h-12 mb-4">calendar_today</mat-icon>
        <p>{{ 'timeline.empty' | translate }}</p>
      </div>
    }

    <div class="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-5 xl:grid-cols-6 gap-4">
      @for (y of years(); track y.year) {
        <button
          class="group flex flex-col rounded-xl overflow-hidden bg-[var(--mat-sys-surface-container)] hover:shadow-lg transition-shadow cursor-pointer text-left"
          (click)="yearSelected.emit(y.year)">
          @if (y.hero_photo_path) {
            <img [src]="y.hero_photo_path | thumbnailUrl:320"
                 [alt]="y.year"
                 class="w-full aspect-[4/3] object-cover" />
          } @else {
            <div class="w-full aspect-[4/3] flex items-center justify-center bg-[var(--mat-sys-surface-container-high)]">
              <mat-icon class="!text-4xl !w-10 !h-10 opacity-30">calendar_today</mat-icon>
            </div>
          }
          <div class="p-3">
            <div class="text-xl font-bold">{{ y.year }}</div>
            <div class="text-sm opacity-60">{{ y.count | number }} {{ 'timeline.photos_count' | translate }}</div>
          </div>
        </button>
      }
    </div>
  `,
})
export class TimelineYearsComponent {
  private readonly api = inject(ApiService);
  private readonly filters = inject(TimelineFiltersService);

  protected readonly years = signal<YearSummary[]>([]);
  protected readonly loading = signal(false);

  readonly yearSelected = output<string>();

  constructor() {
    effect(() => {
      const dateFrom = this.filters.dateFrom();
      const dateTo = this.filters.dateTo();
      this.load(dateFrom, dateTo);
    });
  }

  private async load(dateFrom: string, dateTo: string): Promise<void> {
    this.loading.set(true);
    try {
      const params: Record<string, string> = {};
      if (dateFrom) params['date_from'] = dateFrom;
      if (dateTo) params['date_to'] = dateTo;
      const res = await firstValueFrom(
        this.api.get<{ years: YearSummary[] }>('/timeline/years', params),
      );
      this.years.set(res.years);
    } finally {
      this.loading.set(false);
    }
  }
}
