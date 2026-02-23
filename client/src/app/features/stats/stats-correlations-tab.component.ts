import { Component, inject, signal, computed, viewChild, ElementRef, effect, DestroyRef } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { MatCardModule } from '@angular/material/card';
import { MatButtonModule } from '@angular/material/button';
import { MatFormFieldModule } from '@angular/material/form-field';
import { MatInputModule } from '@angular/material/input';
import { MatSelectModule } from '@angular/material/select';
import { MatIconModule } from '@angular/material/icon';
import { MatProgressSpinnerModule } from '@angular/material/progress-spinner';
import { firstValueFrom } from 'rxjs';
import { Chart } from 'chart.js';
import { ApiService } from '../../core/services/api.service';
import { ThemeService } from '../../core/services/theme.service';
import { TranslatePipe } from '../../shared/pipes/translate.pipe';
import { StatsFiltersService } from './stats-filters.service';

interface CorrelationApiResponse {
  labels: string[];
  metrics?: Record<string, (number | null)[]>;
  groups?: Record<string, Record<string, Record<string, number>>>;
  counts?: number[];
  x_axis: string;
  group_by: string;
}

const COLORS = ['#22c55e', '#3b82f6', '#a855f7', '#f59e0b', '#ef4444', '#06b6d4', '#ec4899', '#84cc16'];

@Component({
  selector: 'app-stats-correlations-tab',
  standalone: true,
  imports: [
    FormsModule,
    MatCardModule,
    MatButtonModule,
    MatFormFieldModule,
    MatInputModule,
    MatSelectModule,
    MatIconModule,
    MatProgressSpinnerModule,
    TranslatePipe,
  ],
  template: `
    <div class="mt-4 flex flex-col gap-4">
      <mat-card>
        <mat-card-header>
          <mat-card-title>{{ 'stats.metric_correlations' | translate }}</mat-card-title>
        </mat-card-header>
        <mat-card-content class="!pt-4">
          <!-- Controls row -->
          <div class="flex flex-wrap items-end gap-3 mb-4">
            <mat-form-field class="w-full md:w-44" subscriptSizing="dynamic">
              <mat-label>{{ 'stats.correlations.x_axis' | translate }}</mat-label>
              <mat-select [ngModel]="corrXAxis()" (ngModelChange)="corrXAxis.set($event)">
                @for (dim of corrDimensions; track dim.key) {
                  <mat-option [value]="dim.key">{{ 'stats.correlations.dimensions.' + dim.key | translate }}</mat-option>
                }
              </mat-select>
            </mat-form-field>
            <mat-form-field class="w-full md:w-64" subscriptSizing="dynamic">
              <mat-label>{{ 'stats.correlations.y_metrics' | translate }}</mat-label>
              <mat-select multiple [ngModel]="corrYMetrics()" (ngModelChange)="corrYMetrics.set($event)">
                @for (m of corrMetricOptions; track m.key) {
                  <mat-option [value]="m.key">{{ 'stats.correlations.metrics.' + m.key | translate }}</mat-option>
                }
              </mat-select>
            </mat-form-field>
            <mat-form-field class="w-full md:w-40" subscriptSizing="dynamic">
              <mat-label>{{ 'stats.correlations.group_by' | translate }}</mat-label>
              <mat-select [ngModel]="corrGroupBy()" (ngModelChange)="corrGroupBy.set($event)">
                <mat-option value="">{{ 'stats.correlations.none' | translate }}</mat-option>
                @for (dim of corrDimensions; track dim.key) {
                  <mat-option [value]="dim.key">{{ 'stats.correlations.dimensions.' + dim.key | translate }}</mat-option>
                }
              </mat-select>
            </mat-form-field>
            <mat-form-field class="w-full md:w-40" subscriptSizing="dynamic">
              <mat-label>{{ 'stats.correlations.chart_type' | translate }}</mat-label>
              <mat-select [ngModel]="corrChartType()" (ngModelChange)="corrChartType.set($event)">
                @for (ct of corrChartTypes; track ct.key) {
                  <mat-option [value]="ct.key">{{ 'stats.correlations.chart_types.' + ct.key | translate }}</mat-option>
                }
              </mat-select>
            </mat-form-field>
            <mat-form-field class="w-full md:w-32" subscriptSizing="dynamic">
              <mat-label>{{ 'stats.correlations.min_samples' | translate }}</mat-label>
              <input matInput type="number" min="1" max="100"
                [ngModel]="corrMinSamples()" (ngModelChange)="corrMinSamples.set($event)">
            </mat-form-field>
            <button mat-stroked-button [disabled]="correlationLoading() || corrYMetrics().length === 0" (click)="loadCorrelation()">
              <mat-icon>refresh</mat-icon>
              {{ 'stats.load_correlations' | translate }}
            </button>
          </div>
          @if (corrYMetrics().length === 0) {
            <div class="text-sm text-gray-400 mb-4">{{ 'stats.correlations.select_metric' | translate }}</div>
          }
          @if (correlationLoading()) {
            <div class="flex justify-center py-4"><mat-spinner diameter="32" /></div>
          } @else if (corrData()) {
            <div class="h-96">
              <canvas #correlationsCanvas></canvas>
            </div>
            @if (corrBucketCount() > 0) {
              <div class="text-xs text-gray-500 mt-2">{{ corrBucketCount() }} {{ 'stats.correlations.buckets' | translate }}</div>
            }
          }
        </mat-card-content>
      </mat-card>
    </div>
  `,
})
export class StatsCorrelationsTabComponent {
  private api = inject(ApiService);
  private destroyRef = inject(DestroyRef);
  private statsFilters = inject(StatsFiltersService);
  private themeService = inject(ThemeService);
  private charts = new Map<string, Chart>();

  readonly correlationsCanvas = viewChild<ElementRef<HTMLCanvasElement>>('correlationsCanvas');

  corrXAxis = signal('date_year');
  corrYMetrics = signal<string[]>(['aggregate', 'aesthetic']);
  corrGroupBy = signal('');
  corrChartType = signal('line');
  corrMinSamples = signal(3);
  corrData = signal<CorrelationApiResponse | null>(null);
  corrBucketCount = computed(() => this.corrData()?.labels?.length ?? 0);
  correlationLoading = signal(false);

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
      const data = this.corrData();
      if (data) this.buildCorrelationChart(data);
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

  async loadCorrelation(): Promise<void> {
    if (this.corrYMetrics().length === 0) return;
    this.correlationLoading.set(true);
    try {
      const params: Record<string, string> = {
        x: this.corrXAxis(),
        y: this.corrYMetrics().join(','),
        min_samples: String(this.corrMinSamples()),
        ...this.filterParams,
      };
      if (this.corrGroupBy()) params['group_by'] = this.corrGroupBy();
      const data = await firstValueFrom(
        this.api.get<CorrelationApiResponse>('/stats/correlations', params),
      );
      this.corrData.set(data);
    } catch { /* empty */ }
    finally { this.correlationLoading.set(false); }
  }

  private buildCorrelationChart(apiData: CorrelationApiResponse): void {
    const ref = this.correlationsCanvas();
    if (!ref || !apiData.labels?.length) return;
    const existing = this.charts.get('correlations');
    if (existing) { existing.destroy(); this.charts.delete('correlations'); }
    const ctx = ref.nativeElement.getContext('2d');
    if (!ctx) return;

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
    }[] = [];

    const themedColors = [this.themeService.accentColor(), ...COLORS.slice(1)];

    if (apiData.groups && Object.keys(apiData.groups).length > 0) {
      const groupNames = Object.keys(apiData.groups);
      for (let gi = 0; gi < groupNames.length; gi++) {
        const grp = groupNames[gi];
        const color = themedColors[gi % themedColors.length];
        const yMetric = this.corrYMetrics()[0] ?? 'aggregate';
        const data = labels.map(lbl => apiData.groups![grp]?.[lbl]?.[yMetric] ?? null);
        datasets.push({
          label: grp, data,
          backgroundColor: color + (type === 'bar' ? 'cc' : '33'),
          borderColor: color, borderWidth: type === 'bar' ? 1 : 2,
          fill, tension: type === 'line' ? 0.3 : undefined,
          pointRadius: type === 'line' ? 2 : undefined,
          borderRadius: type === 'bar' ? 3 : undefined,
        });
      }
    } else if (apiData.metrics) {
      const metricNames = Object.keys(apiData.metrics);
      for (let mi = 0; mi < metricNames.length; mi++) {
        const metric = metricNames[mi];
        const color = themedColors[mi % themedColors.length];
        const values = apiData.metrics[metric] ?? [];
        datasets.push({
          label: metric, data: values,
          backgroundColor: color + (type === 'bar' ? 'cc' : '33'),
          borderColor: color, borderWidth: type === 'bar' ? 1 : 2,
          fill, tension: type === 'line' ? 0.3 : undefined,
          pointRadius: type === 'line' ? 2 : undefined,
          borderRadius: type === 'bar' ? 3 : undefined,
        });
      }
    }

    this.charts.set('correlations', new Chart(ctx, {
      type,
      data: { labels, datasets },
      options: {
        indexAxis: isHorizontal ? 'y' : 'x',
        responsive: true,
        maintainAspectRatio: false,
        plugins: {
          legend: { display: datasets.length > 1, labels: { color: '#d4d4d4', boxWidth: 12 } },
          tooltip: {
            callbacks: {
              label: (tooltipCtx) => {
                const val = isHorizontal ? (tooltipCtx.parsed.x ?? 0) : (tooltipCtx.parsed.y ?? 0);
                return `${tooltipCtx.dataset.label}: ${val.toFixed(2)}`;
              },
            },
          },
        },
        scales: {
          x: {
            grid: { color: isHorizontal ? '#262626' : '#262626' },
            ticks: { color: '#a3a3a3', maxRotation: isHorizontal ? 0 : 45 },
          },
          y: { grid: { color: '#262626' }, ticks: { color: '#d4d4d4', font: { size: 11 } } },
        },
      },
    }));
  }
}
