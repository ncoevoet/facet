import { Component, input, signal, computed, viewChild, ElementRef, effect, DestroyRef, inject } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { MatCardModule } from '@angular/material/card';
import { MatFormFieldModule } from '@angular/material/form-field';
import { MatSelectModule } from '@angular/material/select';
import { MatProgressSpinnerModule } from '@angular/material/progress-spinner';
import { Chart } from 'chart.js';
import 'chartjs-adapter-date-fns';
import { TranslatePipe } from '../../shared/pipes/translate.pipe';
import { ChartHeightPipe } from './chart-height.pipe';

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
  { key: 'avg_composition' },
  { key: 'avg_exposure' },
  { key: 'avg_color' },
  { key: 'avg_iso' },
  { key: 'avg_f_stop' },
  { key: 'avg_focal_length' },
  { key: 'avg_face_count' },
  { key: 'avg_monochrome' },
  { key: 'avg_dynamic_range' },
  { key: 'usage_timeline' },
];

@Component({
  selector: 'app-gear-chart-card',
  standalone: true,
  imports: [
    FormsModule,
    MatCardModule,
    MatFormFieldModule,
    MatSelectModule,
    MatProgressSpinnerModule,
    TranslatePipe,
    ChartHeightPipe,
  ],
  template: `
    <mat-card>
      <mat-card-header class="!flex !items-center !justify-between">
        <mat-card-title>{{ titleKey() | translate }}</mat-card-title>
        <mat-form-field class="w-44 !-mt-2" subscriptSizing="dynamic">
          <mat-select [ngModel]="selectedMetric()" (ngModelChange)="selectedMetric.set($event)">
            @for (opt of metricOptions; track opt.key) {
              <mat-option [value]="opt.key">{{ 'stats.gear_metrics.' + opt.key | translate }}</mat-option>
            }
          </mat-select>
        </mat-form-field>
      </mat-card-header>
      <mat-card-content class="!pt-4">
        @if (loading()) {
          <div class="flex justify-center py-4"><mat-spinner diameter="32" /></div>
        } @else {
          <div [style.height.px]="sortedItems() | chartHeight">
            <canvas #chartCanvas></canvas>
          </div>
        }
      </mat-card-content>
    </mat-card>
  `,
})
export class GearChartCardComponent {
  private destroyRef = inject(DestroyRef);
  private chart: Chart | null = null;

  /** i18n key for the card title, e.g. 'stats.cameras' or 'stats.lenses' */
  readonly titleKey = input.required<string>();
  /** The gear items to display */
  readonly items = input.required<GearItem[]>();
  /** Whether data is still loading */
  readonly loading = input(false);
  /** Chart bar color */
  readonly color = input('#22c55e');

  /** Currently selected metric */
  protected readonly selectedMetric = signal('count');
  protected readonly metricOptions = GEAR_METRIC_OPTIONS;

  /** Canvas ref */
  protected readonly chartCanvas = viewChild<ElementRef<HTMLCanvasElement>>('chartCanvas');

  /** Items sorted by selected metric */
  protected readonly sortedItems = computed(() => this.sortByMetric(this.items(), this.selectedMetric()));

  constructor() {
    // Persistence: Load selected metric from localStorage
    effect(() => {
      const key = this.titleKey();
      const saved = localStorage.getItem(`gear_metric_${key}`);
      if (saved && (this as any).metricOptions.some((opt: any) => opt.key === saved)) {
        (this as any).selectedMetric.set(saved);
      } else {
        // Apply default based on type if no saved value
        if (key === 'stats.cameras') this.selectedMetric.set('usage_timeline');
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
      const color = this.color();

      if (!canvas) return;

      this.destroyChart();
      const ctx = canvas.nativeElement.getContext('2d');
      if (!ctx) return;

      if (metric === 'usage_timeline') {
        const topItems = items.slice(0, 8); // Limit to top 8 to avoid clutter
        const colors = ['#3b82f6', '#10b981', '#f59e0b', '#ef4444', '#8b5cf6', '#ec4899', '#06b6d4', '#eab308'];
        
        this.chart = new Chart(ctx, {
          type: 'line',
          data: {
            datasets: topItems.map((item: GearItem, i: number) => ({
              label: item.name,
              data: item.history.map((h: { date: string; count: number }) => ({ x: h.date, y: h.count })) as any,
              borderColor: colors[i % colors.length],
              backgroundColor: colors[i % colors.length] + '80',
              borderWidth: 2,
              tension: 0.3,
              pointRadius: 2,
            })),
          },
          options: {
            responsive: true,
            maintainAspectRatio: false,
            plugins: {
              legend: { display: true, position: 'bottom', labels: { color: '#d4d4d4', usePointStyle: true, boxWidth: 8 } },
              tooltip: { mode: 'index', intersect: false },
            },
            scales: {
              x: { type: 'time', time: { unit: 'month' }, grid: { color: '#262626' }, ticks: { color: '#a3a3a3' } },
              y: { beginAtZero: true, grid: { color: '#262626' }, ticks: { color: '#d4d4d4' } },
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
              backgroundColor: this.color() + 'cc',
              borderColor: this.color(),
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
              tooltip: { callbacks: { label: (ctx) => (ctx.parsed.x ?? 0).toLocaleString() } },
            },
            scales: {
              x: { grid: { color: '#262626' }, ticks: { color: '#a3a3a3' } },
              y: { grid: { display: false }, ticks: { color: '#d4d4d4', font: { size: 11 } } },
            },
          },
        });
      }
    });

    this.destroyRef.onDestroy(() => this.destroyChart());
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
