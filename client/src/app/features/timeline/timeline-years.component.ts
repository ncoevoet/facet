import { Component, inject, signal, effect, output } from '@angular/core';
import { DecimalPipe } from '@angular/common';
import { MatIconModule } from '@angular/material/icon';
import { MatProgressSpinnerModule } from '@angular/material/progress-spinner';
import { firstValueFrom } from 'rxjs';
import { ApiService } from '../../core/services/api.service';
import { TranslatePipe } from '../../shared/pipes/translate.pipe';
import { ThumbnailUrlPipe } from '../../shared/pipes/thumbnail-url.pipe';
import { TimelineFiltersService } from './timeline-filters.service';
import { I18N } from '../../core/i18n/keys';

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
        <p>{{ I18N.timeline.empty | translate }}</p>
      </div>
    }

    <div class="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-5 xl:grid-cols-6 gap-4">
      @for (y of years(); track y.year) {
        <button
          class="group flex flex-col rounded-xl overflow-hidden bg-[var(--mat-sys-surface-container)] hover:shadow-lg transition-shadow cursor-pointer text-left"
          (click)="yearSelected.emit(y.year)">
          @if (y.hero_photo_path) {
            <div class="relative w-full aspect-[4/3] overflow-hidden">
              <img [src]="y.hero_photo_path | thumbnailUrl:320"
                   [alt]="y.year"
                   class="w-full h-full object-cover group-hover:scale-105 transition-transform duration-300" />
              <div class="absolute inset-x-0 top-0 z-[5] flex items-start gap-1 bg-gradient-to-b from-black/70 to-transparent px-2 pt-1.5 pb-4 pointer-events-none">
                <span class="text-white text-xs font-medium truncate">{{ y.year }}</span>
              </div>
            </div>
          } @else {
            <div class="relative w-full aspect-[4/3] overflow-hidden flex items-center justify-center bg-[var(--mat-sys-surface-container-high)]">
              <mat-icon class="!text-4xl !w-10 !h-10 opacity-30">calendar_today</mat-icon>
              <div class="absolute inset-x-0 top-0 z-[5] flex items-start gap-1 bg-gradient-to-b from-black/70 to-transparent px-2 pt-1.5 pb-4 pointer-events-none">
                <span class="text-white text-xs font-medium truncate">{{ y.year }}</span>
              </div>
            </div>
          }
          <div class="p-3">
            <div class="text-sm opacity-60">{{ y.count | number }} {{ I18N.timeline.photos_count | translate }}</div>
          </div>
        </button>
      }
    </div>
  `,
})
export class TimelineYearsComponent {
  protected readonly I18N = I18N;
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
