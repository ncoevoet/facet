import { Component, inject, signal, computed, viewChild, ElementRef, effect, Pipe, PipeTransform, DestroyRef, Injector, afterNextRender, ChangeDetectionStrategy } from '@angular/core';
import { MatCardModule } from '@angular/material/card';
import { MatProgressSpinnerModule } from '@angular/material/progress-spinner';
import { MatButtonModule } from '@angular/material/button';
import { MatIconModule } from '@angular/material/icon';
import { MatTooltipModule } from '@angular/material/tooltip';
import { firstValueFrom } from 'rxjs';
import { Chart } from 'chart.js';
import { HttpContext } from '@angular/common/http';
import { ApiService } from '../../core/services/api.service';
import { I18nService } from '../../core/services/i18n.service';
import { ThemeService } from '../../core/services/theme.service';
import { AuthService } from '../../core/services/auth.service';
import { TranslatePipe } from '../../shared/pipes/translate.pipe';
import { StatsFiltersService } from './stats-filters.service';
import { statsAuthScope } from './stats-auth-scope';
import { downloadCsv } from '../../shared/utils/csv';
import { LatestRequest } from '../../shared/utils/latest-request';
import { i18nKeys } from '../../core/i18n/keys';
import { chartSeriesColor, chartTheme } from './chart-theme';
import { HANDLE_SERVER_ERROR_LOCALLY } from '../../core/utils/http-error-context';
import { StatsNumberPipe } from './stats-locale-number.pipe';

/** Pipe to compute heatmap circle color from count:max. */
@Pipe({ name: 'heatmapColor', standalone: true })
export class HeatmapColorPipe implements PipeTransform {
  transform(count: number, max: number): string {
    if (count === 0) return 'transparent';
    const pct = Math.round(40 + 60 * (count / max));
    return `color-mix(in srgb, var(--facet-accent) ${pct}%, transparent)`;
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

export function formatStatsMonth(period: string, locale: string): string {
  const match = /^(\d{4})-(\d{2})$/.exec(period);
  if (!match) return period;
  const year = Number(match[1]);
  const month = Number(match[2]);
  if (year < 100 || month < 1 || month > 12) return period;
  return new Intl.DateTimeFormat(locale, { month: 'short', year: 'numeric' }).format(new Date(year, month - 1, 15));
}

@Component({
  selector: 'app-stats-timeline-tab',
  standalone: true,
  imports: [
    MatCardModule,
    MatProgressSpinnerModule,
    MatButtonModule,
    MatIconModule,
    MatTooltipModule,
    TranslatePipe,
    HeatmapColorPipe,
    HeatmapSizePipe,
    StatsNumberPipe,
  ],
  changeDetection: ChangeDetectionStrategy.Eager,
  template: `
    <div class="mt-4 flex flex-col gap-4">
      <mat-card>
        <mat-card-header class="!flex !items-center !justify-between">
          <mat-card-title #timelineHeading tabindex="-1" role="heading" aria-level="2">{{ I18N.stats.photos_over_time | translate }}</mat-card-title>
          <button mat-icon-button class="shrink-0" [disabled]="timeline().length === 0"
            [matTooltip]="I18N.stats.export_csv | translate"
            [attr.aria-label]="I18N.stats.export_csv | translate" (click)="exportCsv()">
            <mat-icon>download</mat-icon>
          </button>
        </mat-card-header>
        <mat-card-content class="!pt-4">
          @if (timelineLoading() && !retrying()) {
            <div class="flex justify-center py-4"><mat-spinner diameter="32" [attr.aria-label]="I18N.ui.labels.loading | translate" /></div>
          } @else if (timelineFailed() || retrying()) {
            <div role="alert" class="flex flex-wrap items-center gap-3 rounded-lg bg-[var(--mat-sys-error-container)] p-4 text-[var(--mat-sys-on-error-container)]">
              <span>{{ (retrying() ? I18N.ui.labels.loading : I18N.stats.correlations.error) | translate }}</span>
              <button #timelineRetry mat-stroked-button class="!min-h-11" [attr.aria-disabled]="retrying()" (click)="retryTimeline()">{{ (retrying() ? I18N.ui.labels.loading : I18N.gallery.load_error.retry) | translate }}</button>
            </div>
          } @else if (!timeline().length) {
            <p class="py-6 text-center text-[var(--mat-sys-on-surface-variant)]">{{ I18N.stats.no_data | translate }}</p>
          } @else {
            <div class="h-64 md:h-80 lg:h-96">
              <canvas #timelineCanvas aria-hidden="true"></canvas>
            </div>
            <details class="mt-3 text-sm text-[var(--mat-sys-on-surface-variant)]">
              <summary class="min-h-11 cursor-pointer content-center">{{ I18N.stats.show_chart_data | translate }}</summary>
              <div class="mt-2 max-h-72 overflow-auto"><table class="w-full text-left">
                <caption class="sr-only">{{ I18N.stats.photos_over_time | translate }}</caption>
                <thead><tr><th scope="col" class="py-1 pr-3">{{ I18N.stats.period | translate }}</th><th scope="col" class="py-1 text-right">{{ I18N.stats.axes.photos | translate }}</th></tr></thead>
                <tbody>
                @for (row of timelineRows(); track row.period) {
                  <tr class="border-b border-[var(--mat-sys-outline-variant)]"><th scope="row" class="py-1 pr-3 font-normal">{{ row.label }}</th><td class="py-1 text-right tabular-nums">{{ row.count | statsNumber:i18n.locale() }}</td></tr>
                }
              </tbody></table></div>
            </details>
          }
        </mat-card-content>
      </mat-card>

      @if (yearlyData().length > 0) {
        <mat-card>
          <mat-card-header>
            <mat-card-title role="heading" aria-level="2">{{ I18N.stats.photos_per_year | translate }}</mat-card-title>
          </mat-card-header>
          <mat-card-content class="!pt-4">
            <div class="h-48 md:h-64">
              <canvas #yearlyCanvas aria-hidden="true"></canvas>
            </div>
            <details class="mt-3 text-sm"><summary class="min-h-11 cursor-pointer content-center">{{ I18N.stats.show_chart_data | translate }}</summary><table class="mt-2 w-full text-left"><caption class="sr-only">{{ I18N.stats.photos_per_year | translate }}</caption><thead><tr><th scope="col">{{ I18N.stats.axes.year | translate }}</th><th scope="col" class="text-right">{{ I18N.stats.axes.photos | translate }}</th></tr></thead><tbody>@for (row of yearlyData(); track row.year) {<tr><th scope="row" class="font-normal">{{ row.year }}</th><td class="text-right">{{ row.count | statsNumber:i18n.locale() }}</td></tr>}</tbody></table></details>
          </mat-card-content>
        </mat-card>
      }

      <div class="grid grid-cols-1 lg:grid-cols-2 gap-4">
        @if (dayOfWeekData().length > 0) {
          <mat-card>
            <mat-card-header>
              <mat-card-title role="heading" aria-level="2">{{ I18N.stats.charts.day_of_week | translate }}</mat-card-title>
            </mat-card-header>
            <mat-card-content class="!pt-4">
              <div class="h-64">
                <canvas #dayOfWeekCanvas aria-hidden="true"></canvas>
              </div>
              <details class="mt-3 text-sm"><summary class="min-h-11 cursor-pointer content-center">{{ I18N.stats.show_chart_data | translate }}</summary><table class="mt-2 w-full text-left"><caption class="sr-only">{{ I18N.stats.charts.day_of_week | translate }}</caption><thead><tr><th scope="col">{{ I18N.stats.axes.day_of_week | translate }}</th><th scope="col" class="text-right">{{ I18N.stats.axes.photos | translate }}</th></tr></thead><tbody>@for (row of dayOfWeekData(); track $index) {<tr><th scope="row" class="font-normal">{{ row.label }}</th><td class="text-right">{{ row.count | statsNumber:i18n.locale() }}</td></tr>}</tbody></table></details>
            </mat-card-content>
          </mat-card>
        }
        @if (hourOfDayData().length > 0) {
          <mat-card>
            <mat-card-header>
              <mat-card-title role="heading" aria-level="2">{{ I18N.stats.charts.hour_of_day | translate }}</mat-card-title>
            </mat-card-header>
            <mat-card-content class="!pt-4">
              <div class="h-64">
                <canvas #hourOfDayCanvas aria-hidden="true"></canvas>
              </div>
              <details class="mt-3 text-sm"><summary class="min-h-11 cursor-pointer content-center">{{ I18N.stats.show_chart_data | translate }}</summary><table class="mt-2 w-full text-left"><caption class="sr-only">{{ I18N.stats.charts.hour_of_day | translate }}</caption><thead><tr><th scope="col">{{ I18N.stats.axes.hour | translate }}</th><th scope="col" class="text-right">{{ I18N.stats.axes.photos | translate }}</th></tr></thead><tbody>@for (row of hourOfDayData(); track $index) {<tr><th scope="row" class="font-normal">{{ row.label }}</th><td class="text-right">{{ row.count | statsNumber:i18n.locale() }}</td></tr>}</tbody></table></details>
            </mat-card-content>
          </mat-card>
        }
      </div>

      @if (heatmapRows().length > 0) {
        <mat-card class="min-w-0">
          <mat-card-header>
            <mat-card-title role="heading" aria-level="2">{{ I18N.stats.charts.hours_heatmap | translate }}</mat-card-title>
          </mat-card-header>
          <mat-card-content class="!pt-4 min-w-0">
            <div class="overflow-x-auto">
              <table class="w-full min-w-[700px] border-collapse text-xs">
                <thead>
                  <tr>
                    <th class="p-1 text-[var(--mat-sys-on-surface-variant)] text-left w-12"></th>
                    @for (h of hours; track h) {
                      <th class="p-1 text-[var(--mat-sys-on-surface-variant)] text-center font-normal">{{ h }}h</th>
                    }
                  </tr>
                </thead>
                <tbody>
                  @for (row of heatmapRows(); track row.day) {
                    <tr>
                      <td class="p-1 text-[var(--mat-sys-on-surface)] font-medium">{{ row.day }}</td>
                      @for (count of row.cells; track $index) {
                        <td class="p-0 text-center align-middle"
                          [title]="I18N.stats.heatmap_tooltip | translate:{day: row.day, hour: $index, count: count}"
                          [attr.aria-label]="I18N.stats.heatmap_tooltip | translate:{day: row.day, hour: $index, count: count}">
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
  protected readonly I18N = i18nKeys();
  private api = inject(ApiService);
  protected i18n = inject(I18nService);
  private destroyRef = inject(DestroyRef);
  private injector = inject(Injector);
  private statsFilters = inject(StatsFiltersService);
  private themeService = inject(ThemeService);
  private auth = inject(AuthService);
  private readonly authScope = statsAuthScope(this.auth);
  private charts = new Map<string, Chart>();
  private readonly latestLoad = new LatestRequest(this.destroyRef);
  private generation = 0;
  private loadedKey = '';

  readonly timelineCanvas = viewChild<ElementRef<HTMLCanvasElement>>('timelineCanvas');
  readonly timelineRetry = viewChild('timelineRetry', { read: ElementRef<HTMLButtonElement> });
  readonly timelineHeading = viewChild('timelineHeading', { read: ElementRef<HTMLElement> });
  readonly yearlyCanvas = viewChild<ElementRef<HTMLCanvasElement>>('yearlyCanvas');
  readonly dayOfWeekCanvas = viewChild<ElementRef<HTMLCanvasElement>>('dayOfWeekCanvas');
  readonly hourOfDayCanvas = viewChild<ElementRef<HTMLCanvasElement>>('hourOfDayCanvas');

  readonly hours = Array.from({ length: 24 }, (_, i) => i);

  timelineLoading = signal(false);
  timelineFailed = signal(false);
  retrying = signal(false);
  timeline = signal<TimelineEntry[]>([]);
  readonly timelineRows = computed(() => this.timeline().map(row => ({ ...row, label: formatStatsMonth(row.period, this.i18n.locale()) })));
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
      this.authScope();
      this.i18n.locale();
      void this.loadTimeline();
    });

    effect(() => {
      const data = this.timelineRows();
      const color = chartSeriesColor(this.themeService.complementaryColor(), this.themeService.darkMode(), 1);
      this.themeService.darkMode(); this.themeService.theme();
      this.buildAreaLine('timeline', this.timelineCanvas(), data.map(t => t.label), data.map(t => t.count), color);
    });
    effect(() => {
      const data = this.yearlyData();
      const accent = chartSeriesColor(this.themeService.accentColor(), this.themeService.darkMode());
      this.themeService.darkMode(); this.themeService.theme();
      this.buildVerticalBar('yearly', this.yearlyCanvas(), data.map(y => y.year), data.map(y => y.count), accent);
    });
    effect(() => {
      const data = this.dayOfWeekData();
      const color = chartSeriesColor(this.themeService.complementaryColor(), this.themeService.darkMode(), 1);
      this.themeService.darkMode(); this.themeService.theme();
      this.buildVerticalBar('dayOfWeek', this.dayOfWeekCanvas(), data.map(d => d.label), data.map(d => d.count), color);
    });
    effect(() => {
      const data = this.hourOfDayData();
      const color = chartSeriesColor(this.themeService.complementaryColor(), this.themeService.darkMode(), 1);
      this.themeService.darkMode(); this.themeService.theme();
      this.buildVerticalBar('hourOfDay', this.hourOfDayCanvas(), data.map(d => d.label), data.map(d => d.count), color);
    });

    this.destroyRef.onDestroy(() => {
      this.generation++;
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

  retryTimeline(): void {
    if (!this.timelineLoading()) void this.loadTimeline(true);
  }

  async loadTimeline(retry = false): Promise<void> {
    const generation = ++this.generation;
    const req = this.latestLoad.begin();
    const key = JSON.stringify([this.auth.identity(), this.auth.isAuthenticated(), this.auth.token, this.filterParams]);
    const button = retry ? this.timelineRetry()?.nativeElement : undefined;
    const doc = button?.ownerDocument;
    const restoreFocus = !!button && doc?.activeElement === button;
    this.timelineLoading.set(true);
    this.retrying.set(retry);
    this.timelineFailed.set(false);
    this.loadedKey = '';
    this.timeline.set([]); this.yearlyData.set([]); this.dayOfWeekData.set([]); this.hourOfDayData.set([]); this.heatmapGrid.set([]); this.heatmapMax.set(1);
    if (!this.auth.isAuthenticated()) { this.timelineLoading.set(false); this.retrying.set(false); return; }
    try {
      const data = await firstValueFrom(req.bind(this.api.get<{
        monthly: { month: string; count: number; avg_score: number }[];
        heatmap?: { day: number; hour: number; count: number }[];
      }>('/stats/timeline', this.filterParams, new HttpContext().set(HANDLE_SERVER_ERROR_LOCALLY, true))));

      if (generation !== this.generation || key !== JSON.stringify([this.auth.identity(), this.auth.isAuthenticated(), this.auth.token, this.filterParams])) return;
      this.loadedKey = key;
      if (restoreFocus && doc?.activeElement === button) {
        afterNextRender(() => {
          if (generation === this.generation && key === JSON.stringify([this.auth.identity(), this.auth.isAuthenticated(), this.auth.token, this.filterParams])
            && (doc.activeElement === doc.body || doc.activeElement === button)) this.timelineHeading()?.nativeElement.focus();
        }, { injector: this.injector });
      }
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
    } catch { if (generation === this.generation && key === JSON.stringify([this.auth.identity(), this.auth.isAuthenticated(), this.auth.token, this.filterParams])) this.timelineFailed.set(true); }
    finally { if (generation === this.generation) { this.timelineLoading.set(false); this.retrying.set(false); } }
  }

  /** Export the monthly photo timeline as CSV. */
  exportCsv(): void {
    if (this.timeline().length === 0 || this.loadedKey !== JSON.stringify([this.auth.identity(), this.auth.isAuthenticated(), this.auth.token, this.filterParams])) return;
    downloadCsv('facet-timeline', this.timeline());
  }

  private buildAreaLine(id: string, ref: ElementRef<HTMLCanvasElement> | undefined, labels: string[], data: number[], color: string): void {
    this.destroyChart(id);
    if (!ref || data.length === 0) return;
    const ctx = ref.nativeElement.getContext('2d');
    if (!ctx) return;
    const palette = chartTheme();
    this.charts.set(id, new Chart(ctx, {
      type: 'line',
      data: {
        labels,
        datasets: [{
          data,
          borderColor: color,
          backgroundColor: color + '33',
          fill: true,
          tension: 0,
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
          tooltip: { callbacks: { label: (ctx) => (ctx.parsed.y ?? 0).toLocaleString(this.i18n.locale()) } },
        },
        scales: {
          x: { grid: { display: false }, ticks: { color: palette.text, maxRotation: 45, autoSkip: true, maxTicksLimit: 24 } },
          y: { grid: { color: palette.grid }, ticks: { color: palette.text }, beginAtZero: true },
        },
      },
    }));
  }

  private buildVerticalBar(id: string, ref: ElementRef<HTMLCanvasElement> | undefined, labels: string[], data: number[], color: string): void {
    this.destroyChart(id);
    if (!ref || data.length === 0) return;
    const ctx = ref.nativeElement.getContext('2d');
    if (!ctx) return;
    const palette = chartTheme();
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
          tooltip: { callbacks: { label: (ctx) => (ctx.parsed.y ?? 0).toLocaleString(this.i18n.locale()) } },
        },
        scales: {
          x: { grid: { display: false }, ticks: { color: palette.text, maxRotation: 45 } },
          y: { grid: { color: palette.grid }, ticks: { color: palette.text } },
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
