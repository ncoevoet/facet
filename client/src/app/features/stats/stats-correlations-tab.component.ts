import { Component, inject, signal, computed, viewChild, ElementRef, effect, DestroyRef, Injector, afterNextRender, ChangeDetectionStrategy } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { MatCardModule } from '@angular/material/card';
import { MatButtonModule } from '@angular/material/button';
import { MatFormFieldModule } from '@angular/material/form-field';
import { MatSelectModule } from '@angular/material/select';
import { MatIconModule } from '@angular/material/icon';
import { MatTooltipModule } from '@angular/material/tooltip';
import { MatProgressSpinnerModule } from '@angular/material/progress-spinner';
import { firstValueFrom } from 'rxjs';
import { Chart, type PointStyle } from 'chart.js';
import { HttpContext } from '@angular/common/http';
import { ApiService } from '../../core/services/api.service';
import { ThemeService } from '../../core/services/theme.service';
import { AuthService } from '../../core/services/auth.service';
import { I18nService } from '../../core/services/i18n.service';
import { TranslatePipe } from '../../shared/pipes/translate.pipe';
import { StatsFiltersService } from './stats-filters.service';
import { downloadCsv } from '../../shared/utils/csv';
import { CorrelationApiResponse, buildCorrelationCsvRecords } from './stats-correlations-csv';
import { i18nKeys } from '../../core/i18n/keys';
import { chartSeriesColors, chartTheme } from './chart-theme';
import { HANDLE_SERVER_ERROR_LOCALLY } from '../../core/utils/http-error-context';

/** Preserve every requested metric for each group, including missing buckets. */
export function correlationSeries(data: CorrelationApiResponse, metrics: string[], metricLabel: (key: string) => string): { label: string; values: (number | null)[]; groupIndex: number; metricIndex: number }[] {
  if (data.groups && Object.keys(data.groups).length) {
    return Object.keys(data.groups).flatMap((group, groupIndex) => metrics.map((metric, metricIndex) => ({
      label: `${group} · ${metricLabel(metric)}`,
      values: data.labels.map(label => data.groups![group]?.[label]?.[metric] ?? null),
      groupIndex, metricIndex,
    })));
  }
  return Object.entries(data.metrics ?? {}).map(([metric, values], metricIndex) => ({ label: metricLabel(metric), values, groupIndex: metricIndex, metricIndex }));
}

@Component({
  selector: 'app-stats-correlations-tab',
  standalone: true,
  imports: [
    FormsModule,
    MatCardModule,
    MatButtonModule,
    MatFormFieldModule,
    MatSelectModule,
    MatIconModule,
    MatTooltipModule,
    MatProgressSpinnerModule,
    TranslatePipe,
  ],
  changeDetection: ChangeDetectionStrategy.Eager,
  template: `
    <div class="mt-4 flex flex-col gap-4">
      <mat-card>
        <mat-card-header class="!flex !items-center !justify-between">
          <mat-card-title #correlationHeading tabindex="-1">{{ I18N.stats.metric_correlations | translate }}</mat-card-title>
          <button mat-icon-button class="shrink-0" [disabled]="!currentData()"
            [matTooltip]="I18N.stats.export_csv | translate"
            [attr.aria-label]="I18N.stats.export_csv | translate" (click)="exportCsv()">
            <mat-icon>download</mat-icon>
          </button>
        </mat-card-header>
        <mat-card-content class="!pt-4">
          <!-- Controls: row 1 — X Axis + Group By -->
          <div class="grid grid-cols-1 sm:grid-cols-2 gap-3 mb-3">
            <mat-form-field subscriptSizing="dynamic">
              <mat-label>{{ I18N.stats.correlations.x_axis | translate }}</mat-label>
              <mat-select [ngModel]="corrXAxis()" (ngModelChange)="corrXAxis.set($event)">
                @for (dim of corrDimensions; track dim.key) {
                  <mat-option [value]="dim.key">{{ 'stats.correlations.dimensions.' + dim.key | translate }}</mat-option>
                }
              </mat-select>
            </mat-form-field>
            <mat-form-field subscriptSizing="dynamic">
              <mat-label>{{ I18N.stats.correlations.group_by | translate }}</mat-label>
              <mat-select [ngModel]="corrGroupBy()" (ngModelChange)="corrGroupBy.set($event)">
                <mat-option value="">{{ I18N.stats.correlations.none | translate }}</mat-option>
                @for (dim of corrDimensions; track dim.key) {
                  <mat-option [value]="dim.key">{{ 'stats.correlations.dimensions.' + dim.key | translate }}</mat-option>
                }
              </mat-select>
            </mat-form-field>
          </div>
          <!-- Controls: row 2 — Metrics + Chart Type + button -->
          <div class="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 items-end gap-3 mb-4">
            <mat-form-field subscriptSizing="dynamic">
              <mat-label>{{ I18N.stats.correlations.y_metrics | translate }}</mat-label>
              <mat-select multiple [ngModel]="corrYMetrics()" (ngModelChange)="corrYMetrics.set($event)">
                @for (m of corrMetricOptions; track m.key) {
                  <mat-option [value]="m.key">{{ 'stats.correlations.metrics.' + m.key | translate }}</mat-option>
                }
              </mat-select>
            </mat-form-field>
            <mat-form-field subscriptSizing="dynamic">
              <mat-label>{{ I18N.stats.correlations.chart_type | translate }}</mat-label>
              <mat-select [ngModel]="corrChartType()" (ngModelChange)="corrChartType.set($event)">
                @for (ct of corrChartTypes; track ct.key) {
                  <mat-option [value]="ct.key">{{ 'stats.correlations.chart_types.' + ct.key | translate }}</mat-option>
                }
              </mat-select>
            </mat-form-field>
            <div class="flex items-end">
              <button mat-stroked-button class="w-full" [disabled]="correlationLoading() || corrYMetrics().length === 0" (click)="loadCorrelation()">
                <mat-icon>refresh</mat-icon>
                {{ I18N.stats.load_correlations | translate }}
              </button>
            </div>
          </div>
          @if (corrYMetrics().length === 0) {
            <div class="text-sm text-[var(--mat-sys-on-surface-variant)] mb-4">{{ I18N.stats.correlations.select_metric | translate }}</div>
          }
          @if (correlationLoading() && !correlationRetrying()) {
            <div class="flex justify-center py-4"><mat-spinner diameter="32" [attr.aria-label]="I18N.ui.labels.loading | translate" /></div>
          } @else if (correlationFailed() || correlationRetrying()) {
            <div role="alert" class="flex flex-wrap items-center gap-3 rounded-lg bg-[var(--mat-sys-error-container)] p-4 text-[var(--mat-sys-on-error-container)]">
              <span>{{ (correlationRetrying() ? I18N.ui.labels.loading : I18N.stats.correlations.error) | translate }}</span>
              <button #correlationRetry mat-stroked-button class="!min-h-11" [attr.aria-disabled]="correlationRetrying()" (click)="retryCorrelation()">{{ (correlationRetrying() ? I18N.ui.labels.loading : I18N.gallery.load_error.retry) | translate }}</button>
            </div>
          } @else if (currentData() && !corrBucketCount()) {
            <p class="py-6 text-center text-[var(--mat-sys-on-surface-variant)]">{{ I18N.stats.no_data | translate }}</p>
          } @else if (currentData()) {
            @if (chartSeriesRows().length > 1) {
              <fieldset class="mb-3 min-w-0 rounded-lg border border-[var(--mat-sys-outline-variant)] px-3 pb-2 pt-1">
                <legend class="px-1 text-xs font-medium text-[var(--mat-sys-on-surface-variant)]">{{ I18N.stats.chart_series | translate }}</legend>
                <div class="grid max-h-32 grid-cols-1 gap-x-4 overflow-auto sm:grid-cols-2">
                  @for (series of chartSeriesRows(); track series.key) {
                    <label class="flex min-h-10 min-w-0 cursor-pointer items-center gap-2 text-sm">
                      <input type="checkbox" class="h-4 w-4 shrink-0 accent-[var(--mat-sys-primary)]" [checked]="series.visible" (change)="setSeriesVisible(series.key, $any($event.target).checked)" />
                      <svg aria-hidden="true" width="32" height="12" class="shrink-0"><line x1="1" y1="6" x2="31" y2="6" [attr.stroke]="series.color" stroke-width="3" [attr.stroke-dasharray]="series.dashPattern" /></svg>
                      <span class="min-w-0 break-words">{{ series.label }}</span>
                    </label>
                  }
                </div>
              </fieldset>
            }
            <div class="h-72 md:h-96 lg:h-[28rem]">
              <canvas #correlationsCanvas aria-hidden="true"></canvas>
            </div>
            <details class="mt-3 text-sm text-[var(--mat-sys-on-surface-variant)]">
              <summary class="cursor-pointer">{{ I18N.stats.show_chart_data | translate }}</summary>
              <div class="mt-2 max-h-72 overflow-auto"><table class="w-full text-left">
                <thead><tr>@for (column of accessibleColumnLabels(); track $index) {<th scope="col" class="p-1">{{ column }}</th>}</tr></thead>
                <tbody>@for (row of accessibleRows(); track $index) {<tr class="border-t border-[var(--mat-sys-outline-variant)]">@for (value of row; track $index) {<td class="p-1">{{ value }}</td>}</tr>}</tbody>
              </table></div>
            </details>
            @if (corrBucketCount() > 0) {
              <div class="text-xs text-[var(--mat-sys-on-surface-variant)] mt-2">{{ corrBucketCount() }} {{ I18N.stats.correlations.buckets | translate }}</div>
            }
          }
        </mat-card-content>
      </mat-card>
    </div>
  `,
})
export class StatsCorrelationsTabComponent {
  protected readonly I18N = i18nKeys();
  private api = inject(ApiService);
  private destroyRef = inject(DestroyRef);
  private statsFilters = inject(StatsFiltersService);
  private themeService = inject(ThemeService);
  private auth = inject(AuthService);
  private i18n = inject(I18nService);
  private injector = inject(Injector);
  private charts = new Map<string, Chart>();
  private generation = 0;
  private readonly loadedKey = signal('');
  private readonly seriesVisibility = signal<Record<string, boolean>>({});

  readonly correlationsCanvas = viewChild<ElementRef<HTMLCanvasElement>>('correlationsCanvas');
  readonly correlationRetry = viewChild('correlationRetry', { read: ElementRef<HTMLButtonElement> });
  readonly correlationHeading = viewChild('correlationHeading', { read: ElementRef<HTMLElement> });

  readonly corrXAxis = signal('date_year');
  readonly corrYMetrics = signal<string[]>(['aggregate', 'aesthetic']);
  readonly corrGroupBy = signal('');
  readonly corrChartType = signal('line');
  readonly corrMinSamples = 3;
  readonly corrData = signal<CorrelationApiResponse | null>(null);
  readonly currentData = computed(() => this.loadedKey() === this.requestKey() ? this.corrData() : null);
  readonly corrBucketCount = computed(() => this.currentData()?.labels?.length ?? 0);
  readonly chartSeriesRows = computed(() => {
    const data = this.currentData();
    if (!data) return [];
    this.i18n.locale();
    const colors = chartSeriesColors(this.themeService.darkMode());
    const bars = this.corrChartType() === 'bar' || this.corrChartType() === 'horizontalBar';
    const dashes = [[], [7, 4], [2, 3], [9, 3, 2, 3]];
    const visibility = this.seriesVisibility();
    return correlationSeries(data, this.corrYMetrics(), metric => this.i18n.t(`stats.correlations.metrics.${metric}`))
      .map(series => {
        const key = `${series.groupIndex}:${series.metricIndex}`;
        const colorIndex = bars && data.groups ? series.groupIndex * this.corrYMetrics().length + series.metricIndex : series.groupIndex;
        const dash = bars ? [] : dashes[series.metricIndex % dashes.length];
        return { ...series, key, color: colors[colorIndex % colors.length], dash, dashPattern: dash.join(' '), visible: visibility[key] !== false };
      });
  });
  private readonly accessibleRecords = computed(() => buildCorrelationCsvRecords(this.currentData(), this.corrYMetrics()));
  readonly accessibleColumns = computed(() => Object.keys(this.accessibleRecords()[0] ?? {}));
  readonly accessibleColumnLabels = computed(() => {
    this.i18n.locale();
    const xAxis = this.currentData()?.x_axis;
    return this.accessibleColumns().map(column => column === 'group'
      ? this.i18n.t(`stats.correlations.dimensions.${this.currentData()?.group_by}`)
      : this.i18n.t(column === xAxis ? `stats.correlations.dimensions.${column}` : `stats.correlations.metrics.${column}`));
  });
  readonly accessibleRows = computed(() => {
    const formatter = new Intl.NumberFormat(this.i18n.locale(), { maximumFractionDigits: 6 });
    return this.accessibleRecords().map(row => this.accessibleColumns().map(column => {
      const value = row[column];
      return typeof value === 'number' ? formatter.format(value) : value ?? '—';
    }));
  });
  readonly correlationLoading = signal(false);
  readonly correlationFailed = signal(false);
  readonly correlationRetrying = signal(false);

  readonly corrDimensions = [
    { key: 'iso' }, { key: 'f_stop' }, { key: 'focal_length' },
    { key: 'camera_model' }, { key: 'lens_model' },
    { key: 'date_month' }, { key: 'date_year' },
    { key: 'composition_pattern' }, { key: 'category' },
    { key: 'aggregate' }, { key: 'aesthetic' }, { key: 'tech_sharpness' },
    { key: 'comp_score' }, { key: 'face_quality' }, { key: 'color_score' },
    { key: 'exposure_score' },
    { key: 'noise_sigma' }, { key: 'contrast_score' }, { key: 'mean_saturation' },
    { key: 'face_ratio' }, { key: 'star_rating' },
  ];

  readonly corrMetricOptions = [
    { key: 'aggregate' }, { key: 'aesthetic' }, { key: 'tech_sharpness' },
    { key: 'noise_sigma' }, { key: 'comp_score' }, { key: 'face_quality' },
    { key: 'color_score' }, { key: 'exposure_score' }, { key: 'contrast_score' },
    { key: 'dynamic_range_stops' }, { key: 'mean_saturation' },
    { key: 'isolation_bonus' }, { key: 'quality_score' },
    { key: 'power_point_score' }, { key: 'leading_lines_score' },
    { key: 'eye_sharpness' }, { key: 'face_sharpness' }, { key: 'face_ratio' },
    { key: 'face_confidence' }, { key: 'histogram_spread' }, { key: 'mean_luminance' },
    { key: 'star_rating' }, { key: 'topiq_score' },
  ];

  readonly corrChartTypes = [
    { key: 'line' }, { key: 'area' }, { key: 'bar' }, { key: 'horizontalBar' },
  ];

  constructor() {
    effect(() => {
      this.corrXAxis(); this.corrYMetrics(); this.corrGroupBy();
      this.statsFilters.filterCategory(); this.statsFilters.dateFrom(); this.statsFilters.dateTo();
      this.auth.status(); this.auth.identity(); this.auth.isAuthenticated();
      this.generation++;
      this.corrData.set(null);
      this.seriesVisibility.set({});
      this.correlationLoading.set(false);
      this.correlationFailed.set(false);
      this.correlationRetrying.set(false);
    });
    effect(() => {
      const data = this.currentData();
      this.themeService.darkMode(); this.themeService.theme(); this.corrChartType(); this.i18n.locale();
      if (data) this.buildCorrelationChart(data);
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

  retryCorrelation(): void {
    if (!this.correlationLoading()) void this.loadCorrelation(true);
  }

  setSeriesVisible(key: string, visible: boolean): void {
    this.seriesVisibility.update(current => ({ ...current, [key]: visible }));
  }

  async loadCorrelation(retry = false): Promise<void> {
    if (!this.auth.isAuthenticated() || this.corrYMetrics().length === 0) return;
    const generation = ++this.generation;
    const key = this.requestKey();
    const button = retry ? this.correlationRetry()?.nativeElement : undefined;
    const doc = button?.ownerDocument;
    const restoreFocus = !!button && doc?.activeElement === button;
    this.correlationLoading.set(true);
    this.correlationRetrying.set(retry);
    this.correlationFailed.set(false);
    this.corrData.set(null);
    try {
      const params: Record<string, string> = {
        x: this.corrXAxis(),
        y: this.corrYMetrics().join(','),
        min_samples: String(this.corrMinSamples),
        ...this.filterParams,
      };
      if (this.corrGroupBy()) params['group_by'] = this.corrGroupBy();
      const data = await firstValueFrom(
        this.api.get<CorrelationApiResponse>('/stats/correlations', params, new HttpContext().set(HANDLE_SERVER_ERROR_LOCALLY, true)),
      );
      if (generation === this.generation && key === this.requestKey()) {
        this.loadedKey.set(key); this.corrData.set(data);
        if (restoreFocus && doc?.activeElement === button) afterNextRender(() => {
          if (generation === this.generation && key === this.requestKey() && (doc.activeElement === doc.body || doc.activeElement === button)) this.correlationHeading()?.nativeElement.focus();
        }, { injector: this.injector });
      }
    } catch { if (generation === this.generation && key === this.requestKey()) this.correlationFailed.set(true); }
    finally { if (generation === this.generation) { this.correlationLoading.set(false); this.correlationRetrying.set(false); } }
  }

  /** Export the loaded correlation buckets as CSV (one row per bucket, or per bucket+group). */
  exportCsv(): void {
    const data = this.currentData();
    if (this.loadedKey() !== this.requestKey() || !data || !data.labels?.length) return;
    downloadCsv('facet-correlations', buildCorrelationCsvRecords(data, this.corrYMetrics()));
  }

  private requestKey(): string {
    // Token rotation revalidates/replaces status even when the user id stays
    // the same. Track that signal so cached data is invalidated immediately.
    this.auth.status();
    return JSON.stringify([this.auth.identity(), this.auth.isAuthenticated(), this.auth.token, this.corrXAxis(), this.corrYMetrics(), this.corrGroupBy(),
      this.statsFilters.filterCategory(), this.statsFilters.dateFrom(), this.statsFilters.dateTo()]);
  }

  private buildCorrelationChart(apiData: CorrelationApiResponse): void {
    const ref = this.correlationsCanvas();
    if (!ref || !apiData.labels?.length) return;
    const existing = this.charts.get('correlations');
    if (existing) { existing.destroy(); this.charts.delete('correlations'); }
    const ctx = ref.nativeElement.getContext('2d');
    if (!ctx) return;
    const palette = chartTheme();

    const labels = apiData.labels;
    const chartType = this.corrChartType();
    const isHorizontal = chartType === 'horizontalBar';
    const type: 'bar' | 'line' = (chartType === 'bar' || chartType === 'horizontalBar') ? 'bar' : 'line';
    const fill = chartType === 'area';

    const datasets: {
      label: string;
      data: (number | null)[];
      backgroundColor: string;
      borderColor: string;
      borderWidth: number;
      fill?: boolean;
      tension?: number;
      pointRadius?: number;
      borderRadius?: number;
      borderDash?: number[];
      pointStyle?: PointStyle;
    }[] = [];

    const points: PointStyle[] = ['circle', 'triangle', 'rect', 'rectRot', 'crossRot', 'star'];
    for (const series of this.chartSeriesRows().filter(row => row.visible)) {
        const color = series.color;
        datasets.push({
          label: series.label, data: series.values,
          backgroundColor: color + (type === 'bar' ? 'cc' : '33'),
          borderColor: color, borderWidth: type === 'bar' ? 1 : 2,
          fill, tension: type === 'line' ? 0 : undefined,
          borderDash: type === 'line' ? series.dash : undefined,
          pointStyle: type === 'line' ? points[series.groupIndex % points.length] : undefined,
          pointRadius: type === 'line' ? 3 : undefined,
          borderRadius: type === 'bar' ? 3 : undefined,
        });
    }

    this.charts.set('correlations', new Chart(ctx, {
      type,
      data: { labels, datasets },
      options: {
        indexAxis: isHorizontal ? 'y' : 'x',
        responsive: true,
        maintainAspectRatio: false,
        plugins: {
          legend: { display: false },
          tooltip: {
            callbacks: {
              label: (tooltipCtx) => {
                const val = isHorizontal ? (tooltipCtx.parsed.x ?? 0) : (tooltipCtx.parsed.y ?? 0);
                return `${tooltipCtx.dataset.label}: ${new Intl.NumberFormat(this.i18n.locale(), { maximumFractionDigits: 2 }).format(val)}`;
              },
            },
          },
        },
        scales: {
          x: {
            grid: { color: palette.grid },
            ticks: { color: palette.text, maxRotation: isHorizontal ? 0 : 45 },
          },
          y: { grid: { color: palette.grid }, ticks: { color: palette.text, font: { size: 11 } } },
        },
      },
    }));
  }
}
