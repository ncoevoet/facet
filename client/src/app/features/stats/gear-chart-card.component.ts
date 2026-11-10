import { Component, input, signal, computed, viewChild, ElementRef, effect, DestroyRef, inject, ChangeDetectionStrategy } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { MatCardModule } from '@angular/material/card';
import { MatFormFieldModule } from '@angular/material/form-field';
import { MatSelectModule } from '@angular/material/select';
import { MatProgressSpinnerModule } from '@angular/material/progress-spinner';
import { MatButtonModule } from '@angular/material/button';
import { MatIconModule } from '@angular/material/icon';
import { MatTooltipModule } from '@angular/material/tooltip';
import { Chart, type ChartType, type LegendItem, type PointStyle } from 'chart.js';
import 'chartjs-adapter-date-fns';
import { ThemeService } from '../../core/services/theme.service';
import { I18nService } from '../../core/services/i18n.service';
import { TranslatePipe } from '../../shared/pipes/translate.pipe';
import { SortOptionIconPipe } from '../../shared/pipes/sort-option-icon.pipe';
import { ChartHeightPipe } from './chart-height.pipe';
import { downloadCsv } from '../../shared/utils/csv';
import { chartSeriesColor, chartSeriesColors, chartTheme } from './chart-theme';
import { StatsNumberPipe } from './stats-locale-number.pipe';

export const GEAR_LEGEND_MAX_CHARS = 24;

/** Shortens a legend label to `max` characters with a trailing ellipsis; the dataset label (tooltip) stays full. */
export function truncateLegendLabel(text: string, max: number = GEAR_LEGEND_MAX_CHARS): string {
  return text.length > max ? text.slice(0, max - 1).trimEnd() + '…' : text;
}

/** Chart.js legend items with their text shortened so a narrow canvas never clips the point marker. */
export function truncatedLegendLabels(chart: Chart): LegendItem[] {
  const base = Chart.defaults.plugins.legend.labels.generateLabels(chart as Chart<ChartType>);
  return base.map(item => ({ ...item, text: truncateLegendLabel(item.text) }));
}

export interface GearItem {
  name: string;
  count: number;
  avg_score: number;
  avg_aesthetic: number;
  avg_sharpness: number;
  avg_composition: number;
  avg_exposure: number;
  avg_color: number;
  avg_iso: number;
  avg_f_stop: number;
  avg_focal_length: number;
  avg_face_count: number;
  avg_monochrome: number;
  avg_dynamic_range: number;
  history: { date: string; count: number }[];
}

const GEAR_METRIC_OPTIONS = [
  { key: 'count' },
  { key: 'avg_score' },
  { key: 'avg_aesthetic' },
  { key: 'avg_sharpness' },
  { key: 'avg_iso' },
  { key: 'avg_f_stop' },
  { key: 'avg_focal_length' },
  { key: 'usage_timeline' },
];

@Component({
  selector: 'app-gear-chart-card',
  standalone: true,
  host: { class: 'block' },
  imports: [
    FormsModule,
    MatCardModule,
    MatFormFieldModule,
    MatSelectModule,
    MatProgressSpinnerModule,
    MatButtonModule,
    MatIconModule,
    MatTooltipModule,
    TranslatePipe,
    SortOptionIconPipe,
    ChartHeightPipe,
    StatsNumberPipe,
  ],
  changeDetection: ChangeDetectionStrategy.Eager,
  template: `
    <mat-card>
      <mat-card-header class="!flex !flex-wrap !items-center !justify-between !gap-3">
        <mat-card-title role="heading" aria-level="2" class="shrink-0">{{ titleKey() | translate }}</mat-card-title>
        <mat-form-field class="flex-1 min-w-[10rem] !-mt-2 max-sm:order-last max-sm:basis-full" subscriptSizing="dynamic">
          <!-- No mat-label: the card title next to it already names the chart,
               and repeating it read as a rendering glitch. The aria-label gives
               the select the accessible name the visible label used to. -->
          <mat-select [ngModel]="selectedMetric()" (ngModelChange)="selectedMetric.set($event)"
                      [aria-label]="'stats.gear_metric_label' | translate">
            <mat-select-trigger>
              @let selectedIcon = selectedMetric() | sortOptionIcon;
              <span class="inline-flex max-w-full items-center align-top">
                <mat-icon aria-hidden="true" class="!w-8 shrink-0 text-center" [class]="selectedIcon.classes">{{ selectedIcon.text }}</mat-icon>
                <span class="truncate">{{ 'stats.gear_metrics.' + selectedMetric() | translate }}</span>
              </span>
            </mat-select-trigger>
            @for (opt of metricOptions; track opt.key) {
              @let optionIcon = opt.key | sortOptionIcon;
              <mat-option [value]="opt.key">
                <mat-icon aria-hidden="true" class="!w-8 text-center" [class]="optionIcon.classes">{{ optionIcon.text }}</mat-icon>
                {{ 'stats.gear_metrics.' + opt.key | translate }}
              </mat-option>
            }
          </mat-select>
        </mat-form-field>
        <button mat-icon-button class="shrink-0 max-sm:ml-auto" [disabled]="items().length === 0"
          [matTooltip]="'stats.export_csv' | translate"
          [attr.aria-label]="'stats.export_csv' | translate" (click)="exportCsv()">
          <mat-icon>download</mat-icon>
        </button>
      </mat-card-header>
      <mat-card-content class="!pt-4">
        @if (loading()) {
          <div class="flex justify-center py-4"><mat-spinner diameter="32" [attr.aria-label]="'ui.labels.loading' | translate" /></div>
        } @else if (items().length === 0) {
          <p class="py-6 text-center text-[var(--mat-sys-on-surface-variant)]">{{ 'stats.no_data' | translate }}</p>
        } @else {
          <div [style.height.px]="sortedItems() | chartHeight">
            <canvas #chartCanvas aria-hidden="true"></canvas>
          </div>
            <details class="mt-3 text-sm text-[var(--mat-sys-on-surface-variant)]">
              <summary class="min-h-11 cursor-pointer content-center">{{ 'stats.show_chart_data' | translate }}</summary>
              <div class="mt-2 max-h-72 overflow-auto"><table class="w-full text-left">
                <caption class="sr-only">{{ titleKey() | translate }}</caption>
                <thead><tr><th scope="col" class="py-1 pr-3">{{ 'stats.model' | translate }}</th><th scope="col" class="py-1 text-right">{{ ('stats.gear_metrics.' + selectedMetric()) | translate }}</th></tr></thead>
                <tbody>
                @for (row of accessibleRows(); track $index) {
                  <tr class="border-b border-[var(--mat-sys-outline-variant)]"><th scope="row" class="py-1 pr-3 font-normal">{{ row.name }}</th><td class="py-1 text-right tabular-nums">{{ row.value | statsNumber:i18n.locale():valueDigits() }}</td></tr>
                }
              </tbody></table></div>
            </details>
        }
      </mat-card-content>
    </mat-card>
  `,
})
export class GearChartCardComponent {
  private readonly destroyRef = inject(DestroyRef);
  private readonly themeService = inject(ThemeService);
  protected readonly i18n = inject(I18nService);
  private chart: Chart | null = null;

  /** i18n key for the card title, e.g. 'stats.cameras' or 'stats.lenses' */
  readonly titleKey = input.required<string>();
  /** The gear items to display */
  readonly items = input.required<GearItem[]>();
  /** Whether data is still loading */
  readonly loading = input(false);
  /** Chart bar color */
  readonly color = input('');

  /** Currently selected metric */
  protected readonly selectedMetric = signal('count');
  protected readonly metricOptions = GEAR_METRIC_OPTIONS;

  /** Canvas ref */
  protected readonly chartCanvas = viewChild<ElementRef<HTMLCanvasElement>>('chartCanvas');

  /** Items sorted by selected metric */
  protected readonly sortedItems = computed(() => this.sortByMetric(this.items(), this.selectedMetric()));
  /** Counts and ISO/focal length are whole numbers; the averaged scores and f-stop keep one decimal. */
  protected readonly valueDigits = computed(() => ['count', 'usage_timeline', 'avg_iso', 'avg_focal_length'].includes(this.selectedMetric()) ? 0 : 1);
  protected readonly accessibleRows = computed(() => this.selectedMetric() === 'usage_timeline'
    ? this.sortedItems().slice(0, 8).flatMap(item => item.history.map(point => ({ name: `${item.name} · ${point.date}`, value: point.count })))
    : this.sortedItems().map(item => ({ name: item.name, value: this.metricValue(item, this.selectedMetric()) })));

  constructor() {
    // Persistence: Load selected metric from localStorage
    effect(() => {
      const key = this.titleKey();
      const saved = localStorage.getItem(`gear_metric_${key}`);
      if (saved && this.metricOptions.some(opt => opt.key === saved)) {
        this.selectedMetric.set(saved);
      } else {
        // Apply default based on type if no saved value
        if (key === 'stats.cameras') this.selectedMetric.set('count');
        else if (key === 'stats.lenses') this.selectedMetric.set('avg_score');
        else if (key === 'stats.charts.camera_lens_combos') this.selectedMetric.set('count');
      }
    });

    // Persistence: Save selected metric to localStorage
    effect(() => {
      const key = this.titleKey();
      const metric = this.selectedMetric();
      localStorage.setItem(`gear_metric_${key}`, metric);
    });

    // Rebuild chart when data, metric, or canvas changes
    effect(() => {
      const items = this.sortedItems();
      const metric = this.selectedMetric();
      const canvas = this.chartCanvas();
      const dark = this.themeService.darkMode();
      const color = chartSeriesColor(this.color() || this.themeService.accentColor(), dark, this.titleKey() === 'stats.lenses' ? 1 : 0);
      this.themeService.theme();
      this.i18n.locale();

      if (!canvas) return;

      this.destroyChart();
      const ctx = canvas.nativeElement.getContext('2d');
      if (!ctx) return;
      const palette = chartTheme();

      if (metric === 'usage_timeline') {
        const topItems = items.slice(0, 8); // Limit to top 8 to avoid clutter
        const colors = chartSeriesColors(dark);
        const dashes = [[], [7, 4], [2, 3], [9, 3, 2, 3]];
        const points: PointStyle[] = ['circle', 'triangle', 'rect', 'rectRot', 'crossRot', 'star'];
        
        this.chart = new Chart(ctx, {
          type: 'line',
          data: {
            datasets: topItems.map((item: GearItem, i: number) => ({
              label: item.name,
              data: item.history.map((h: { date: string; count: number }) => ({ x: h.date, y: h.count })) as any,
              borderColor: colors[i % colors.length],
              backgroundColor: colors[i % colors.length] + '80',
              borderWidth: 2,
              borderDash: dashes[i % dashes.length],
              tension: 0,
              pointRadius: 3,
              pointStyle: points[i % points.length],
            })),
          },
          options: {
            responsive: true,
            maintainAspectRatio: false,
            plugins: {
              legend: { display: true, position: 'bottom', labels: { color: palette.text, usePointStyle: true, boxWidth: 8, generateLabels: truncatedLegendLabels } },
              tooltip: {
                mode: 'index',
                intersect: false,
                callbacks: {
                  // Each point is a whole month bucketed at the first of the
                  // month, so Chart.js's default title ("Mar 1, 2026, 12:00:00
                  // a.m.") reports a moment that was never measured. Same
                  // month-year form the x ticks use; T00:00:00 keeps the
                  // string parsed in the local zone, not UTC.
                  title: (items) => {
                    const x = (items[0]?.raw as { x?: string } | undefined)?.x ?? '';
                    const d = new Date(x + 'T00:00:00');
                    return Number.isNaN(d.getTime()) ? x
                      : new Intl.DateTimeFormat(this.i18n.locale(), { month: 'short', year: 'numeric' }).format(d);
                  },
                },
              },
            },
            scales: {
              x: { type: 'time', time: { unit: 'month' }, grid: { color: palette.grid }, ticks: { color: palette.text } },
              y: { beginAtZero: true, grid: { color: palette.grid }, ticks: { color: palette.text } },
            },
          }
        });
      } else {
        // Standard Bar Chart
        const values = items.map((d: GearItem) => this.metricValue(d, metric));
        const labels = items.map((d: GearItem) => d.name);

        this.chart = new Chart(ctx, {
          type: 'bar',
          data: {
            labels,
            datasets: [{
              data: values,
              backgroundColor: color + 'cc',
              borderColor: color,
              borderWidth: 1,
              borderRadius: 2,
            }],
          },
          options: {
            indexAxis: 'y',
            responsive: true,
            maintainAspectRatio: false,
            plugins: {
              legend: { display: false },
              tooltip: { callbacks: { label: (ctx) => (ctx.parsed.x ?? 0).toLocaleString(this.i18n.locale()) } },
            },
            scales: {
              x: { grid: { color: palette.grid }, ticks: { color: palette.text } },
              y: { grid: { display: false }, ticks: { color: palette.text, font: { size: 11 }, callback: function(value) { return truncateLegendLabel(this.getLabelForValue(Number(value)), canvas.nativeElement.clientWidth < 420 ? 14 : 24); } } },
            },
          },
        });
      }
    });

    this.destroyRef.onDestroy(() => this.destroyChart());
  }

  /** Export the card's gear rows as a CSV file. */
  protected exportCsv(): void {
    const slug = this.titleKey().split('.').pop() ?? 'gear';
    downloadCsv(`facet-${slug}`, this.items());
  }

  private destroyChart(): void {
    if (this.chart) {
      this.chart.destroy();
      this.chart = null;
    }
  }

  private metricValue(item: GearItem, metric: string): number {
    switch (metric) {
      case 'count': return item.count;
      case 'avg_score': return item.avg_score;
      case 'avg_aesthetic': return item.avg_aesthetic;
      case 'avg_sharpness': return item.avg_sharpness;
      case 'avg_composition': return item.avg_composition;
      case 'avg_exposure': return item.avg_exposure;
      case 'avg_color': return item.avg_color;
      case 'avg_iso': return item.avg_iso;
      case 'avg_f_stop': return item.avg_f_stop;
      case 'avg_focal_length': return item.avg_focal_length;
      case 'avg_face_count': return item.avg_face_count;
      case 'avg_monochrome': return item.avg_monochrome;
      case 'avg_dynamic_range': return item.avg_dynamic_range;
      default: return item.count;
    }
  }

  private sortByMetric(items: GearItem[], metric: string): GearItem[] {
    if (metric === 'usage_timeline') {
      return [...items].sort((a, b) => b.count - a.count); // For timeline, prioritize the most used gear
    }
    return [...items].sort((a, b) => this.metricValue(b, metric) - this.metricValue(a, metric));
  }
}
