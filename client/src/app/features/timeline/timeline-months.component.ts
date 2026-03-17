import { Component, inject, signal, input, effect, output } from '@angular/core';
import { DatePipe, DecimalPipe } from '@angular/common';
import { MatIconModule } from '@angular/material/icon';
import { MatProgressSpinnerModule } from '@angular/material/progress-spinner';
import { firstValueFrom } from 'rxjs';
import { ApiService } from '../../core/services/api.service';
import { TranslatePipe } from '../../shared/pipes/translate.pipe';
import { ThumbnailUrlPipe } from '../../shared/pipes/thumbnail-url.pipe';

interface MonthSummary {
  month: string;
  count: number;
  hero_photo_path: string | null;
}

@Component({
  selector: 'app-timeline-months',
  standalone: true,
  imports: [DecimalPipe, MatIconModule, MatProgressSpinnerModule, TranslatePipe, ThumbnailUrlPipe],
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

    <div class="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-6 gap-4">
      @for (m of months(); track m.month) {
        <button
          class="group flex flex-col rounded-xl overflow-hidden bg-[var(--mat-sys-surface-container)] hover:shadow-lg transition-shadow cursor-pointer text-left"
          (click)="monthSelected.emit(m.month)">
          @if (m.hero_photo_path) {
            <img [src]="m.hero_photo_path | thumbnailUrl:320"
                 [alt]="m.month"
                 class="w-full aspect-[4/3] object-cover" />
          } @else {
            <div class="w-full aspect-[4/3] flex items-center justify-center bg-[var(--mat-sys-surface-container-high)]">
              <mat-icon class="!text-4xl !w-10 !h-10 opacity-30">calendar_today</mat-icon>
            </div>
          }
          <div class="p-3">
            <div class="text-lg font-semibold">{{ formatMonth(m.month) }}</div>
            <div class="text-sm opacity-60">{{ m.count | number }} {{ 'timeline.photos_count' | translate }}</div>
          </div>
        </button>
      }
    </div>
  `,
})
export class TimelineMonthsComponent {
  private readonly api = inject(ApiService);
  private readonly datePipe = new DatePipe('en-US');

  readonly year = input.required<string>();
  readonly monthSelected = output<string>();

  protected readonly months = signal<MonthSummary[]>([]);
  protected readonly loading = signal(false);

  constructor() {
    effect(() => {
      const y = this.year();
      if (y) this.load(y);
    });
  }

  private async load(year: string): Promise<void> {
    this.loading.set(true);
    try {
      const res = await firstValueFrom(
        this.api.get<{ months: MonthSummary[] }>('/timeline/months', { year: +year }),
      );
      this.months.set(res.months);
    } finally {
      this.loading.set(false);
    }
  }

  protected formatMonth(monthStr: string): string {
    // monthStr is "2025-03" format
    return this.datePipe.transform(new Date(monthStr + '-15T12:00:00'), 'MMMM') ?? monthStr;
  }
}
