import { Component, inject, signal, computed, viewChild, ElementRef, effect, Pipe, PipeTransform, DestroyRef } from '@angular/core';
import { MatCardModule } from '@angular/material/card';
import { MatProgressSpinnerModule } from '@angular/material/progress-spinner';
import { firstValueFrom } from 'rxjs';
import { Chart } from 'chart.js';
import { ApiService } from '../../core/services/api.service';
import { I18nService } from '../../core/services/i18n.service';
import { TranslatePipe } from '../../shared/pipes/translate.pipe';
import { StatsFiltersService } from './stats-filters.service';

/** Pipe to compute heatmap circle color from count:max. */
@Pipe({ name: 'heatmapColor', standalone: true })
export class HeatmapColorPipe implements PipeTransform {
  transform(count: number, max: number): string {
    if (count === 0) return 'transparent';
    const ratio = count / max;
    const g = Math.round(80 + 175 * ratio);
    const alpha = 0.4 + 0.6 * ratio;
    return `rgba(34, ${g}, 94, ${alpha})`;
  }
}

/** Pipe to compute heatmap circle size from count:max. */
@Pipe({ name: 'heatmapSize', standalone: true })
export class HeatmapSizePipe implements PipeTransform {
  transform(count: number, max: number): number {
    if (count === 0) return 0;
    const ratio = count / max;
    return Math.max(4, Math.round(Math.sqrt(ratio) * 28));
  }
}

interface TimelineEntry {
  period: string;
  count: number;
  avg_score: number;
}

@Component({
  selector: 'app-stats-timeline-tab',
  standalone: true,
  imports: [
    MatCardModule,
    MatProgressSpinnerModule,
    TranslatePipe,
    HeatmapColorPipe,
    HeatmapSizePipe,
  ],
  template: `
    <div class="mt-4 flex flex-col gap-4">
      <mat-card>
        <mat-card-header>
          <mat-card-title>{{ 'stats.photos_over_time' | translate }}</mat-card-title>
        </mat-card-header>
        <mat-card-content class="!pt-4">
          @if (timelineLoading()) {
            <div class="flex justify-center py-4"><mat-spinner diameter="32" /></div>
          } @else {
            <div class="h-80">
              <canvas #timelineCanvas></canvas>
            </div>
          }
        </mat-card-content>
      </mat-card>

      @if (yearlyData().length > 0) {
        <mat-card>
          <mat-card-header>
            <mat-card-title>{{ 'stats.photos_per_year' | translate }}</mat-card-title>
          </mat-card-header>
          <mat-card-content class="!pt-4">
            <div class="h-64">
              <canvas #yearlyCanvas></canvas>
            </div>
          </mat-card-content>
        </mat-card>
      }

      <div class="grid grid-cols-1 lg:grid-cols-2 gap-4">
        @if (dayOfWeekData().length > 0) {
          <mat-card>
            <mat-card-header>
              <mat-card-title>{{ 'stats.charts.day_of_week' | translate }}</mat-card-title>
            </mat-card-header>
            <mat-card-content class="!pt-4">
              <div class="h-64">
                <canvas #dayOfWeekCanvas></canvas>
              </div>
            </mat-card-content>
          </mat-card>
        }
        @if (hourOfDayData().length > 0) {
          <mat-card>
            <mat-card-header>
              <mat-card-title>{{ 'stats.charts.hour_of_day' | translate }}</mat-card-title>
            </mat-card-header>
            <mat-card-content class="!pt-4">
              <div class="h-64">
                <canvas #hourOfDayCanvas></canvas>
              </div>
            </mat-card-content>
          </mat-card>
        }
      </div>

      @if (heatmapRows().length > 0) {
        <mat-card>
          <mat-card-header>
            <mat-card-title>{{ 'stats.charts.hours_heatmap' | translate }}</mat-card-title>
          </mat-card-header>
          <mat-card-content class="!pt-4">
            <div class="overflow-x-auto">
              <table class="w-full border-collapse text-xs">
                <thead>
                  <tr>
                    <th class="p-1 text-gray-400 text-left w-12"></th>
                    @for (h of hours; track h) {
                      <th class="p-1 text-gray-400 text-center font-normal">{{ h }}h</th>
                    }
                  </tr>
                </thead>
                <tbody>
                  @for (row of heatmapRows(); track $index) {
                    <tr>
                      <td class="p-1 text-gray-300 font-medium">{{ row.day }}</td>
                      @for (count of row.cells; track $index) {
                        <td class="p-0 text-center align-middle"
                          [title]="'stats.heatmap_tooltip' | translate:{day: row.day, hour: $index, count: count}">
                          <div class="inline-block rounded-full"
                            [style.width.px]="count | heatmapSize:heatmapMax()"
                            [style.height.px]="count | heatmapSize:heatmapMax()"
                            [style.background-color]="count | heatmapColor:heatmapMax()">
                          </div>
                        </td>
                      }
                    </tr>
                  }
                </tbody>
              </table>
            </div>
          </mat-card-content>
        </mat-card>
      }
    </div>
  `,
})
export class StatsTimelineTabComponent {
  private api = inject(ApiService);
  private i18n = inject(I18nService);
  private destroyRef = inject(DestroyRef);
  private statsFilters = inject(StatsFiltersService);
  private charts = new Map<string, Chart>();

  readonly timelineCanvas = viewChild<ElementRef<HTMLCanvasElement>>('timelineCanvas');
  readonly yearlyCanvas = viewChild<ElementRef<HTMLCanvasElement>>('yearlyCanvas');
  readonly dayOfWeekCanvas = viewChild<ElementRef<HTMLCanvasElement>>('dayOfWeekCanvas');
  readonly hourOfDayCanvas = viewChild<ElementRef<HTMLCanvasElement>>('hourOfDayCanvas');

  readonly hours = Array.from({ length: 24 }, (_, i) => i);

  timelineLoading = signal(false);
  timeline = signal<TimelineEntry[]>([]);
  yearlyData = signal<{ year: string; count: number }[]>([]);
  dayOfWeekData = signal<{ label: string; count: number }[]>([]);
  hourOfDayData = signal<{ label: string; count: number }[]>([]);
  heatmapGrid = signal<number[][]>([]);
  heatmapMax = signal(1);

  private readonly dayKeys = ['sun', 'mon', 'tue', 'wed', 'thu', 'fri', 'sat'];

  heatmapRows = computed(() =>
    this.heatmapGrid().map((cells, i) => ({ day: this.i18n.t('stats.days.' + this.dayKeys[i]), cells })),
  );

  constructor() {
    effect(() => {
      this.statsFilters.filterCategory();
      this.statsFilters.dateFrom();
      this.statsFilters.dateTo();
      void this.loadTimeline();
    });

    effect(() => {
      const data = this.timeline();
      this.buildAreaLine('timeline', this.timelineCanvas(), data.map(t => t.period), data.map(t => t.count), '#22c55e');
    });
    effect(() => {
      const data = this.yearlyData();
      this.buildVerticalBar('yearly', this.yearlyCanvas(), data.map(y => y.year), data.map(y => y.count), '#22c55e');
    });
    effect(() => {
      const data = this.dayOfWeekData();
      this.buildVerticalBar('dayOfWeek', this.dayOfWeekCanvas(), data.map(d => d.label), data.map(d => d.count), '#a855f7');
    });
    effect(() => {
      const data = this.hourOfDayData();
      this.buildVerticalBar('hourOfDay', this.hourOfDayCanvas(), data.map(d => d.label), data.map(d => d.count), '#06b6d4');
    });

    this.destroyRef.onDestroy(() => {
      this.charts.forEach(chart => chart.destroy());
      this.charts.clear();
    });
  }

  private get filterParams(): Record<string, string> {
    const params: Record<string, string> = {};
    if (this.statsFilters.dateFrom()) params['date_from'] = this.statsFilters.dateFrom();
    if (this.statsFilters.dateTo()) params['date_to'] = this.statsFilters.dateTo();
    if (this.statsFilters.filterCategory()) params['category'] = this.statsFilters.filterCategory();
    return params;
  }

  async loadTimeline(): Promise<void> {
    this.timelineLoading.set(true);
    try {
      const data = await firstValueFrom(this.api.get<{
        monthly: { month: string; count: number; avg_score: number }[];
        heatmap?: { day: number; hour: number; count: number }[];
      }>('/stats/timeline', this.filterParams));

      const monthly = data.monthly ?? [];
      this.timeline.set(monthly.map(m => ({ period: m.month, count: m.count, avg_score: m.avg_score ?? 0 })));

      const yearMap = new Map<string, number>();
      for (const m of monthly) {
        const year = m.month.substring(0, 4);
        yearMap.set(year, (yearMap.get(year) ?? 0) + m.count);
      }
      this.yearlyData.set([...yearMap.entries()].map(([year, count]) => ({ year, count })));

      const heatmap = data.heatmap ?? [];
      if (heatmap.length > 0) {
        const dayNames = this.dayKeys.map(k => this.i18n.t('stats.days.' + k));
        const dayCounts = new Array(7).fill(0);
        const hourCounts = new Array(24).fill(0);
        for (const entry of heatmap) {
          if (entry.day >= 0 && entry.day < 7) dayCounts[entry.day] += entry.count;
          if (entry.hour >= 0 && entry.hour < 24) hourCounts[entry.hour] += entry.count;
        }
        this.dayOfWeekData.set(dayNames.map((label, i) => ({ label, count: dayCounts[i] })));
        this.hourOfDayData.set(hourCounts.map((count, i) => ({ label: `${i}h`, count })));

        const grid: number[][] = Array.from({ length: 7 }, () => new Array(24).fill(0));
        let maxVal = 1;
        for (const entry of heatmap) {
          if (entry.day >= 0 && entry.day < 7 && entry.hour >= 0 && entry.hour < 24) {
            grid[entry.day][entry.hour] = entry.count;
            if (entry.count > maxVal) maxVal = entry.count;
          }
        }
        this.heatmapGrid.set(grid);
        this.heatmapMax.set(maxVal);
      }
    } catch { /* empty */ }
    finally { this.timelineLoading.set(false); }
  }

  private buildAreaLine(id: string, ref: ElementRef<HTMLCanvasElement> | undefined, labels: string[], data: number[], color: string): void {
    if (!ref || data.length === 0) return;
    this.destroyChart(id);
    const ctx = ref.nativeElement.getContext('2d');
    if (!ctx) return;
    this.charts.set(id, new Chart(ctx, {
      type: 'line',
      data: {
        labels,
        datasets: [{
          data,
          borderColor: color,
          backgroundColor: color + '33',
          fill: true,
          tension: 0.3,
          pointRadius: 0,
          pointHitRadius: 8,
          borderWidth: 2,
        }],
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        plugins: {
          legend: { display: false },
          tooltip: { callbacks: { label: (ctx) => (ctx.parsed.y ?? 0).toLocaleString() } },
        },
        scales: {
          x: { grid: { display: false }, ticks: { color: '#a3a3a3', maxRotation: 45, autoSkip: true, maxTicksLimit: 24 } },
          y: { grid: { color: '#262626' }, ticks: { color: '#a3a3a3' }, beginAtZero: true },
        },
      },
    }));
  }

  private buildVerticalBar(id: string, ref: ElementRef<HTMLCanvasElement> | undefined, labels: string[], data: number[], color: string): void {
    if (!ref || data.length === 0) return;
    this.destroyChart(id);
    const ctx = ref.nativeElement.getContext('2d');
    if (!ctx) return;
    this.charts.set(id, new Chart(ctx, {
      type: 'bar',
      data: {
        labels,
        datasets: [{
          data,
          backgroundColor: color + 'cc',
          borderColor: color,
          borderWidth: 1,
          borderRadius: 3,
        }],
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        plugins: {
          legend: { display: false },
          tooltip: { callbacks: { label: (ctx) => (ctx.parsed.y ?? 0).toLocaleString() } },
        },
        scales: {
          x: { grid: { display: false }, ticks: { color: '#a3a3a3', maxRotation: 45 } },
          y: { grid: { color: '#262626' }, ticks: { color: '#a3a3a3' } },
        },
      },
    }));
  }

  private destroyChart(id: string): void {
    const existing = this.charts.get(id);
    if (existing) {
      existing.destroy();
      this.charts.delete(id);
    }
  }
}
