import { Component, inject, signal, computed, viewChild, ElementRef, effect, DestroyRef, Injector, afterNextRender, ChangeDetectionStrategy, untracked, WritableSignal, input } from '@angular/core';
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
import { SortOptionIconPipe } from '../../shared/pipes/sort-option-icon.pipe';
import { TranslatePipe } from '../../shared/pipes/translate.pipe';
import { StatsFiltersService } from './stats-filters.service';
import { downloadCsv } from '../../shared/utils/csv';
import { CorrelationApiResponse, buildCorrelationCsvRecords, correlationBucketColumn } from './stats-correlations-csv';
import { i18nKeys } from '../../core/i18n/keys';
import { statsAuthScope } from './stats-auth-scope';
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

/** A suggested chart: the form values it fills in. The first one is the tab's default. */
export interface CorrelationPreset { id: string; x: string; y: readonly string[]; groupBy: string; chart: string }

export const CORRELATION_PRESETS: readonly CorrelationPreset[] = [
  { id: 'scores_by_year', x: 'date_year', y: ['aggregate', 'aesthetic'], groupBy: '', chart: 'line' },
  { id: 'noise_vs_iso', x: 'iso', y: ['noise_sigma'], groupBy: 'camera_model', chart: 'line' },
  { id: 'score_by_category', x: 'category', y: ['aggregate', 'aesthetic'], groupBy: '', chart: 'horizontalBar' },
  { id: 'score_by_focal_length', x: 'focal_length', y: ['aggregate', 'aesthetic'], groupBy: '', chart: 'bar' },
];
const [DEFAULT_PRESET] = CORRELATION_PRESETS;
const sameList = (a: readonly string[], b: readonly string[]): boolean => a.length === b.length && a.every((value, index) => value === b[index]);

const LINE_POINT_STYLES: PointStyle[] = ['circle', 'triangle', 'rect', 'rectRot', 'crossRot', 'star'];

/** Preserve slots for still-visible series, reusing only slots that became free. */
export function allocateSeriesSlots(keys: string[], previous: Record<string, number>, limit = 8): Record<string, number> {
  const slots: Record<string, number> = {};
  const used = new Set<number>();
  for (const key of keys) {
    const slot = previous[key];
    if (slot !== undefined && slot >= 0 && slot < limit && !used.has(slot)) { slots[key] = slot; used.add(slot); }
  }
  for (const key of keys) {
    if (slots[key] !== undefined) continue;
    const slot = Array.from({ length: limit }, (_, index) => index).find(index => !used.has(index));
    if (slot === undefined) break;
    slots[key] = slot; used.add(slot);
  }
  return slots;
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
    SortOptionIconPipe,
  ],
  changeDetection: ChangeDetectionStrategy.Eager,
  template: `
    <div class="mt-4 flex flex-col gap-4">
      <mat-card>
        <mat-card-header class="!flex !items-center !justify-between">
          <mat-card-title #correlationHeading tabindex="-1" role="heading" aria-level="2">{{ I18N.stats.metric_correlations | translate }}</mat-card-title>
          <button mat-icon-button class="shrink-0" [disabled]="!currentData()"
            [matTooltip]="I18N.stats.export_csv | translate"
            [attr.aria-label]="I18N.stats.export_csv | translate" (click)="exportCsv()">
            <mat-icon>download</mat-icon>
          </button>
        </mat-card-header>
        <mat-card-content class="!pt-4">
          <div role="group" aria-labelledby="correlation-presets-label" class="mb-4 flex flex-wrap items-center gap-2">
            <span id="correlation-presets-label" class="text-sm text-[var(--mat-sys-on-surface-variant)]">{{ I18N.stats.correlations.presets.label | translate }}</span>
            @for (preset of presets; track preset.id) {
              @let presetIcon = preset.x | sortOptionIcon;
              <button type="button" mat-stroked-button data-correlation-preset class="pointer-coarse:!min-h-11"
                [class.!bg-[var(--mat-sys-secondary-container)]]="activePreset() === preset.id"
                [attr.aria-pressed]="activePreset() === preset.id" (click)="applyPreset(preset)">
                <mat-icon aria-hidden="true" [class]="presetIcon.classes">{{ presetIcon.text }}</mat-icon>
                {{ 'stats.correlations.presets.' + preset.id | translate }}
              </button>
            }
          </div>
          <!-- Controls: row 1 — X Axis + Group By -->
          <div class="grid grid-cols-1 sm:grid-cols-2 gap-3 mb-3">
            <mat-form-field subscriptSizing="dynamic">
              <mat-label>{{ I18N.stats.correlations.x_axis | translate }}</mat-label>
              <mat-select [ngModel]="corrXAxis()" (ngModelChange)="edit(corrXAxis, $event)">
                <mat-select-trigger>
                  @let xAxisIcon = corrXAxis() | sortOptionIcon;
                  <mat-icon aria-hidden="true" class="!w-8 text-center" [class]="xAxisIcon.classes">{{ xAxisIcon.text }}</mat-icon>
                  {{ 'stats.correlations.dimensions.' + corrXAxis() | translate }}
                </mat-select-trigger>
                @for (dim of corrDimensions; track dim.key) {
                  @let xOptionIcon = dim.key | sortOptionIcon;
                  <mat-option [value]="dim.key">
                    <mat-icon aria-hidden="true" class="!w-8 text-center" [class]="xOptionIcon.classes">{{ xOptionIcon.text }}</mat-icon>
                    {{ 'stats.correlations.dimensions.' + dim.key | translate }}
                  </mat-option>
                }
              </mat-select>
            </mat-form-field>
            <mat-form-field subscriptSizing="dynamic">
              <mat-label>{{ I18N.stats.correlations.group_by | translate }}</mat-label>
              <mat-select [ngModel]="corrGroupBy()" (ngModelChange)="edit(corrGroupBy, $event)">
                <mat-select-trigger>
                  @if (corrGroupBy()) {
                    @let groupIcon = corrGroupBy() | sortOptionIcon;
                    <mat-icon aria-hidden="true" class="!w-8 text-center" [class]="groupIcon.classes">{{ groupIcon.text }}</mat-icon>
                    {{ 'stats.correlations.dimensions.' + corrGroupBy() | translate }}
                  } @else {
                    {{ I18N.stats.correlations.none | translate }}
                  }
                </mat-select-trigger>
                <mat-option value="">{{ I18N.stats.correlations.none | translate }}</mat-option>
                @for (dim of corrDimensions; track dim.key) {
                  @let groupOptionIcon = dim.key | sortOptionIcon;
                  <mat-option [value]="dim.key">
                    <mat-icon aria-hidden="true" class="!w-8 text-center" [class]="groupOptionIcon.classes">{{ groupOptionIcon.text }}</mat-icon>
                    {{ 'stats.correlations.dimensions.' + dim.key | translate }}
                  </mat-option>
                }
              </mat-select>
            </mat-form-field>
          </div>
          <!-- Controls: row 2 — Metrics + Chart Type + button -->
          <div class="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 items-end gap-3 mb-4">
            <mat-form-field subscriptSizing="dynamic">
              <mat-label>{{ I18N.stats.correlations.y_metrics | translate }}</mat-label>
              <mat-select multiple [ngModel]="corrYMetrics()" (ngModelChange)="edit(corrYMetrics, $event)">
                @for (m of corrMetricOptions; track m.key) {
                  @let metricIcon = m.key | sortOptionIcon;
                  <mat-option [value]="m.key">
                    <mat-icon aria-hidden="true" class="!w-8 text-center" [class]="metricIcon.classes">{{ metricIcon.text }}</mat-icon>
                    {{ 'stats.correlations.metrics.' + m.key | translate }}
                  </mat-option>
                }
              </mat-select>
            </mat-form-field>
            <mat-form-field subscriptSizing="dynamic">
              <mat-label>{{ I18N.stats.correlations.chart_type | translate }}</mat-label>
              <mat-select [ngModel]="corrChartType()" (ngModelChange)="setChartType($event)">
                <mat-select-trigger>
                  @let chartTypeIcon = corrChartType() | sortOptionIcon;
                  <mat-icon aria-hidden="true" class="!w-8 text-center" [class]="chartTypeIcon.classes">{{ chartTypeIcon.text }}</mat-icon>
                  {{ 'stats.correlations.chart_types.' + corrChartType() | translate }}
                </mat-select-trigger>
                @for (ct of corrChartTypes; track ct.key) {
                  @let chartOptionIcon = ct.key | sortOptionIcon;
                  <mat-option [value]="ct.key">
                    <mat-icon aria-hidden="true" class="!w-8 text-center" [class]="chartOptionIcon.classes">{{ chartOptionIcon.text }}</mat-icon>
                    {{ 'stats.correlations.chart_types.' + ct.key | translate }}
                  </mat-option>
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
              <fieldset aria-describedby="correlation-series-help" class="mb-3 min-w-0 rounded-lg border border-[var(--mat-sys-outline-variant)] px-3 pb-2 pt-1">
                <legend class="px-1 text-xs font-medium text-[var(--mat-sys-on-surface-variant)]">{{ I18N.stats.chart_series | translate }}</legend>
                <div id="correlation-series-help" class="mb-1 text-xs text-[var(--mat-sys-on-surface-variant)]" aria-live="polite">
                  <span>{{ I18N.stats.series_selected_count | translate:{selected: selectedSeriesCount(), total: chartSeriesRows().length} }}</span>
                  @if (isBarChart() && chartSeriesRows().length > seriesLimit) { <span> · {{ I18N.stats.series_limit | translate:{count: seriesLimit} }}</span> }
                  @if (chartSeriesRows().length > 3) { <span class="sm:hidden"> · {{ I18N.stats.more_series_scroll | translate }}</span> }
                  @if (chartSeriesRows().length > 6) { <span class="hidden sm:inline"> · {{ I18N.stats.more_series_scroll | translate }}</span> }
                </div>
                <button type="button" mat-button class="!min-h-10 !px-2" (click)="resetSeriesSelection()">{{ I18N.stats.reset_series | translate }}</button>
                <div class="grid max-h-32 grid-cols-1 gap-x-4 overflow-auto sm:grid-cols-2">
                  @for (series of chartSeriesRows(); track series.key) {
                    <label class="flex min-h-10 min-w-0 cursor-pointer items-center gap-2 text-sm" [class.opacity-60]="series.atLimit">
                      <input type="checkbox" class="h-4 w-4 shrink-0 accent-[var(--mat-sys-primary)]" [checked]="series.visible" [disabled]="series.atLimit" (change)="setSeriesVisible(series.key, $any($event.target).checked)" />
                      <svg aria-hidden="true" width="32" height="12" class="shrink-0" [class.opacity-30]="!series.visible"><line x1="1" y1="6" x2="31" y2="6" [attr.stroke]="series.color" stroke-width="3" [attr.stroke-dasharray]="series.dashPattern" /></svg>
                      <span class="min-w-0 break-words">{{ series.label }}</span>
                    </label>
                  }
                </div>
              </fieldset>
            }
            @if (selectedSeriesCount() === 0) {
              <p role="status" class="py-8 text-center text-[var(--mat-sys-on-surface-variant)]">{{ I18N.stats.no_series_selected | translate }}</p>
            } @else {
              <div class="h-72 md:h-96 lg:h-[28rem]">
                <canvas #correlationsCanvas aria-hidden="true"></canvas>
              </div>
            }
            <details class="mt-3 text-sm text-[var(--mat-sys-on-surface-variant)]">
              <summary class="min-h-11 cursor-pointer content-center">{{ I18N.stats.show_chart_data | translate }}</summary>
              <div class="mt-2 max-h-72 overflow-auto"><table class="w-full text-left">
                <caption class="sr-only">{{ I18N.stats.metric_correlations | translate }}</caption>
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
  private readonly authScope = statsAuthScope(this.auth);
  private i18n = inject(I18nService);
  private injector = inject(Injector);
  private charts = new Map<string, Chart>();
  private generation = 0;
  private readonly loadedKey = signal('');
  private readonly seriesVisibility = signal<Record<string, boolean>>({});
  private readonly barColorSlots = signal<Record<string, number>>({});

  readonly correlationsCanvas = viewChild<ElementRef<HTMLCanvasElement>>('correlationsCanvas');
  readonly correlationRetry = viewChild('correlationRetry', { read: ElementRef<HTMLButtonElement> });
  readonly correlationHeading = viewChild('correlationHeading', { read: ElementRef<HTMLElement> });

  readonly presets = CORRELATION_PRESETS;
  readonly corrXAxis = signal(DEFAULT_PRESET.x);
  readonly corrYMetrics = signal<string[]>([...DEFAULT_PRESET.y], { equal: sameList });
  readonly corrGroupBy = signal(DEFAULT_PRESET.groupBy);
  readonly corrChartType = signal(DEFAULT_PRESET.chart);
  /** The preset the form currently matches, so its chip shows as selected. */
  readonly activePreset = computed(() => CORRELATION_PRESETS.find(preset => preset.x === this.corrXAxis() && preset.groupBy === this.corrGroupBy()
    && preset.chart === this.corrChartType() && sameList(preset.y, this.corrYMetrics()))?.id ?? null);
  /** Until the user edits the form, a settings or filter change redraws the chart by itself. */
  private autoLoad = true;
  /** False while the stats page shows another tab, so a hidden chart is not queried. */
  readonly active = input(true);
  readonly corrMinSamples = 3;
  readonly corrData = signal<CorrelationApiResponse | null>(null);
  readonly seriesLimit = 8;
  readonly isBarChart = computed(() => this.corrChartType() === 'bar' || this.corrChartType() === 'horizontalBar');
  readonly currentData = computed(() => this.loadedKey() === this.requestKey() ? this.corrData() : null);
  readonly corrBucketCount = computed(() => this.currentData()?.labels?.length ?? 0);
  readonly chartSeriesRows = computed(() => {
    const data = this.currentData();
    if (!data) return [];
    this.i18n.locale();
    const colors = chartSeriesColors(this.themeService.darkMode());
    const bars = this.isBarChart();
    const dashes = [[], [7, 4], [2, 3], [9, 3, 2, 3]];
    const visibility = this.seriesVisibility();
    const barSlots = this.barColorSlots();
    let visibleIndex = 0;
    const rows = correlationSeries(data, this.corrYMetrics(), metric => this.i18n.t(`stats.correlations.metrics.${metric}`))
      .map((series, index) => {
        const key = `${series.groupIndex}:${series.metricIndex}`;
        const requested = visibility[key] ?? (!bars || index < this.seriesLimit);
        const visible = requested && (!bars || visibleIndex < this.seriesLimit);
        const colorIndex = bars ? (visible ? (barSlots[key] ?? visibleIndex++) : 0) : series.groupIndex;
        if (bars && visible && barSlots[key] !== undefined) visibleIndex++;
        // Lines keep colour for the group; dash, then point shape, tell its metrics apart (4 dashes x 6 points = 24 metrics).
        const dash = bars ? [] : dashes[series.metricIndex % dashes.length];
        const point = LINE_POINT_STYLES[Math.floor(series.metricIndex / dashes.length) % LINE_POINT_STYLES.length];
        return { ...series, key, color: bars && !visible ? 'var(--mat-sys-outline)' : colors[colorIndex % colors.length], dash, dashPattern: dash.join(' '), point, visible };
      });
    const selected = rows.filter(row => row.visible).length;
    return rows.map(row => ({ ...row, atLimit: bars && !row.visible && selected >= this.seriesLimit }));
  });
  readonly selectedSeriesCount = computed(() => this.chartSeriesRows().filter(row => row.visible).length);
  private readonly accessibleRecords = computed(() => buildCorrelationCsvRecords(this.currentData(), this.corrYMetrics()));
  readonly accessibleColumns = computed(() => Object.keys(this.accessibleRecords()[0] ?? {}));
  readonly accessibleColumnLabels = computed(() => {
    this.i18n.locale();
    const data = this.currentData();
    const bucketColumn = data ? correlationBucketColumn(data, this.corrYMetrics()) : '';
    return this.accessibleColumns().map(column => column === 'group'
      ? this.i18n.t(`stats.correlations.dimensions.${data?.group_by}`)
      : this.i18n.t(column === bucketColumn ? `stats.correlations.dimensions.${data?.x_axis}` : `stats.correlations.metrics.${column}`));
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
      this.authScope();
      this.generation++;
      this.corrData.set(null);
      this.seriesVisibility.set({});
      this.barColorSlots.set({});
      this.correlationLoading.set(false);
      this.correlationFailed.set(false);
      this.correlationRetrying.set(false);
      if (this.autoLoad && untracked(this.active)) untracked(() => void this.loadCorrelation());
    });
    effect(() => {
      if (this.active()) untracked(() => {
        if (this.autoLoad && !this.currentData() && !this.correlationLoading() && !this.correlationFailed()) void this.loadCorrelation();
      });
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

  /** A form edit: the chart waits for Load, as the user may change several fields first. */
  edit<T>(field: WritableSignal<T>, value: T): void {
    this.autoLoad = false;
    field.set(value);
  }

  /** Fill the form from a suggested chart and draw it. */
  applyPreset(preset: CorrelationPreset): void {
    const key = this.requestKey();
    this.autoLoad = true;
    this.corrXAxis.set(preset.x);
    this.corrYMetrics.set([...preset.y]);
    this.corrGroupBy.set(preset.groupBy);
    this.setChartType(preset.chart);
    // Unchanged settings do not rerun the reset effect, so load here when nothing is shown yet.
    if (key === this.requestKey() && !this.currentData() && !this.correlationLoading()) void this.loadCorrelation();
  }

  retryCorrelation(): void {
    if (!this.correlationLoading()) void this.loadCorrelation(true);
  }

  setSeriesVisible(key: string, visible: boolean): void {
    if (visible && this.isBarChart() && this.selectedSeriesCount() >= this.seriesLimit) return;
    if (this.isBarChart()) {
      const keys = this.chartSeriesRows().filter(row => row.visible && row.key !== key).map(row => row.key);
      if (visible) keys.push(key);
      this.barColorSlots.set(allocateSeriesSlots(keys, this.barColorSlots(), this.seriesLimit));
    }
    this.seriesVisibility.update(current => ({ ...current, [key]: visible }));
  }

  resetSeriesSelection(): void {
    if (this.isBarChart()) {
      const keys = this.chartSeriesRows().slice(0, this.seriesLimit).map(row => row.key);
      this.barColorSlots.set(allocateSeriesSlots(keys, this.barColorSlots(), this.seriesLimit));
    }
    this.seriesVisibility.set({});
  }

  setChartType(type: string): void {
    const nextIsBar = type === 'bar' || type === 'horizontalBar';
    if (nextIsBar && !this.isBarChart()) {
      let selected = 0;
      const visibility: Record<string, boolean> = {};
      for (const row of this.chartSeriesRows()) {
        visibility[row.key] = row.visible && selected < this.seriesLimit;
        if (visibility[row.key]) selected++;
      }
      this.barColorSlots.set(allocateSeriesSlots(Object.keys(visibility).filter(key => visibility[key]), {}, this.seriesLimit));
      this.seriesVisibility.set(visibility);
    }
    this.corrChartType.set(type);
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
        if (this.isBarChart()) {
          const keys = correlationSeries(data, this.corrYMetrics(), metric => metric).slice(0, this.seriesLimit).map(row => `${row.groupIndex}:${row.metricIndex}`);
          this.barColorSlots.set(allocateSeriesSlots(keys, {}, this.seriesLimit));
        }
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
    // The scope tracks identity and token changes, so a status refresh that changes neither does not
    // invalidate cached data; the live token still rejects a response that returns after a rotation.
    return JSON.stringify([this.authScope(), this.auth.token, this.corrXAxis(), this.corrYMetrics(), this.corrGroupBy(),
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

    for (const series of this.chartSeriesRows().filter(row => row.visible)) {
        const color = series.color;
        datasets.push({
          label: series.label, data: series.values,
          backgroundColor: color + (type === 'bar' ? 'cc' : '33'),
          borderColor: color, borderWidth: type === 'bar' ? 1 : 2,
          fill, tension: type === 'line' ? 0 : undefined,
          borderDash: type === 'line' ? series.dash : undefined,
          pointStyle: type === 'line' ? series.point : undefined,
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
            ...(type === 'bar' && isHorizontal ? { beginAtZero: true } : {}),
          },
          y: { grid: { color: palette.grid }, ticks: { color: palette.text, font: { size: 11 } }, ...(type === 'bar' && !isHorizontal ? { beginAtZero: true } : {}) },
        },
      },
    }));
  }
}
