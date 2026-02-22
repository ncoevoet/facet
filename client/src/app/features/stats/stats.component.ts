import { Component, inject, signal, computed, viewChild, ElementRef, effect, Pipe, PipeTransform, DestroyRef } from '@angular/core';
import { DecimalPipe } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { MatCardModule } from '@angular/material/card';
import { MatTabsModule } from '@angular/material/tabs';
import { MatIconModule } from '@angular/material/icon';
import { MatButtonModule } from '@angular/material/button';
import { MatProgressSpinnerModule } from '@angular/material/progress-spinner';
import { MatFormFieldModule } from '@angular/material/form-field';
import { MatInputModule } from '@angular/material/input';
import { MatSelectModule } from '@angular/material/select';
import { firstValueFrom } from 'rxjs';
import { Router, ActivatedRoute } from '@angular/router';
import { Chart, registerables } from 'chart.js';
import { ApiService } from '../../core/services/api.service';
import { I18nService } from '../../core/services/i18n.service';
import { TranslatePipe } from '../../shared/pipes/translate.pipe';
import { StatsFiltersService } from './stats-filters.service';
import { GearChartCardComponent, GearItem } from './gear-chart-card.component';

import { ChartHeightPipe } from './chart-height.pipe';

Chart.register(...registerables);
Chart.defaults.color = '#a3a3a3';
Chart.defaults.borderColor = '#262626';



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

interface StatsOverview {
  total_photos: number;
  total_persons: number;
  avg_score: number;
  avg_aesthetic: number;
  avg_composition: number;
  total_faces: number;
  total_tags: number;
  date_range_start: string;
  date_range_end: string;
}



interface GearApiResponse {
  cameras: GearItem[];
  lenses: GearItem[];
  combos: { name: string; count: number; avg_aggregate: number }[];
  categories: { name: string; count: number }[];
}

interface CategoryStat {
  category: string;
  count: number;
  percentage: number;
  avg_score: number;
  avg_aesthetic: number;
  avg_composition: number;
  avg_sharpness: number;
  avg_color: number;
  avg_exposure: number;
  avg_face_quality: number;
  avg_contrast: number;
  avg_iso: number;
  avg_f_stop: number;
  avg_focal_length: number;
  top_camera: string | null;
  top_lens: string | null;
}

interface ScoreBin {
  range: string;
  min: number;
  max: number;
  count: number;
  percentage: number;
}

interface TimelineEntry {
  period: string;
  count: number;
  avg_score: number;
}

interface TopCamera {
  name: string;
  count: number;
  avg_score: number;
  avg_aesthetic: number;
}

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
  selector: 'app-stats',
  imports: [
    DecimalPipe,
    FormsModule,
    MatCardModule,
    MatTabsModule,
    MatIconModule,
    MatButtonModule,
    MatProgressSpinnerModule,
    MatFormFieldModule,
    MatInputModule,
    MatSelectModule,
    TranslatePipe,
    ChartHeightPipe,
    HeatmapColorPipe,
    HeatmapSizePipe,
    GearChartCardComponent,
  ],
  host: { class: 'block' },
  template: `
    <div class="p-4 md:p-6 max-w-7xl mx-auto">
      @if (loading()) {
        <div class="flex justify-center py-16">
          <mat-spinner diameter="48" />
        </div>
      } @else {
        <!-- Overview cards -->
        @if (overview()) {
          <div class="grid grid-cols-2 md:grid-cols-4 gap-4 mb-6">
            <mat-card>
              <mat-card-content class="!py-4 text-center">
                <mat-icon class="!text-4xl !w-10 !h-10 text-blue-400 mb-1">photo_library</mat-icon>
                <div class="text-3xl font-bold">{{ overview()!.total_photos | number }}</div>
                <div class="text-sm text-gray-400">{{ 'stats.total_photos' | translate }}</div>
              </mat-card-content>
            </mat-card>
            <mat-card>
              <mat-card-content class="!py-4 text-center">
                <mat-icon class="!text-4xl !w-10 !h-10 text-purple-400 mb-1">people</mat-icon>
                <div class="text-3xl font-bold">{{ overview()!.total_persons | number }}</div>
                <div class="text-sm text-gray-400">{{ 'stats.total_persons' | translate }}</div>
              </mat-card-content>
            </mat-card>
            <mat-card>
              <mat-card-content class="!py-4 text-center">
                <mat-icon class="!text-4xl !w-10 !h-10 text-amber-400 mb-1">star</mat-icon>
                <div class="text-3xl font-bold">{{ overview()!.avg_score | number:'1.1-1' }}</div>
                <div class="text-sm text-gray-400">{{ 'stats.avg_score' | translate }}</div>
              </mat-card-content>
            </mat-card>
            <mat-card>
              <mat-card-content class="!py-4 text-center">
                <mat-icon class="!text-4xl !w-10 !h-10 text-green-400 mb-1">face</mat-icon>
                <div class="text-3xl font-bold">{{ overview()!.total_faces | number }}</div>
                <div class="text-sm text-gray-400">{{ 'stats.total_faces' | translate }}</div>
              </mat-card-content>
            </mat-card>
          </div>
        }

        <mat-tab-group [selectedIndex]="selectedTab()" (selectedIndexChange)="selectedTab.set($event)">
          <!-- Gear tab -->
          <mat-tab>
            <ng-template mat-tab-label>
              <mat-icon class="mr-2">camera_alt</mat-icon>
              {{ 'stats.gear' | translate }}
            </ng-template>
            <div class="flex flex-col gap-4 mt-4">
              <!-- Camera block -->
              <app-gear-chart-card
                titleKey="stats.cameras"
                [items]="cameras()"
                [loading]="gearLoading()"
                color="#22c55e" />
              <!-- Lenses block -->
              <app-gear-chart-card
                titleKey="stats.lenses"
                [items]="lenses()"
                [loading]="gearLoading()"
                color="#3b82f6" />
              <!-- Combos block -->
              @if (combos().length > 0) {
                <app-gear-chart-card
                  titleKey="stats.charts.camera_lens_combos"
                  [items]="combos()"
                  [loading]="gearLoading()"
                  color="#f59e0b" />
              }
            </div>
          </mat-tab>

          <!-- Categories tab -->
          <mat-tab>
            <ng-template mat-tab-label>
              <mat-icon class="mr-2">category</mat-icon>
              {{ 'stats.categories.tab' | translate }}
            </ng-template>
            <div class="mt-4 flex flex-col gap-4">

              <!-- Row 1: Distribution + Score Profile -->
              <div class="grid grid-cols-1 lg:grid-cols-2 gap-4">
                <mat-card>
                  <mat-card-header>
                    <mat-card-title>{{ 'stats.category_distribution' | translate }}</mat-card-title>
                  </mat-card-header>
                  <mat-card-content class="!pt-4">
                    @if (categoriesLoading()) {
                      <div class="flex justify-center py-4"><mat-spinner diameter="32" /></div>
                    } @else {
                      <div [style.height.px]="categoryStats() | chartHeight">
                        <canvas #categoriesCanvas></canvas>
                      </div>
                    }
                  </mat-card-content>
                </mat-card>

                @if (categoryScoreProfile().length > 0) {
                  <mat-card>
                    <mat-card-header>
                      <mat-card-title>{{ 'stats.categories_score_profile' | translate }}</mat-card-title>
                    </mat-card-header>
                    <mat-card-content class="!pt-4">
                      @if (categoriesLoading()) {
                        <div class="flex justify-center py-4"><mat-spinner diameter="32" /></div>
                      } @else {
                        <div [style.height.px]="categoryScoreProfile() | chartHeight:80">
                          <canvas #categoryScoreProfileCanvas></canvas>
                        </div>
                      }
                    </mat-card-content>
                  </mat-card>
                }
              </div>

              <!-- Row 2: Aperture + Focal Length -->
              <div class="grid grid-cols-1 lg:grid-cols-2 gap-4">
                @if (categoryApertureProfile().length > 0) {
                  <mat-card>
                    <mat-card-header>
                      <mat-card-title>{{ 'stats.categories_aperture' | translate }}</mat-card-title>
                    </mat-card-header>
                    <mat-card-content class="!pt-4">
                      <div [style.height.px]="categoryApertureProfile() | chartHeight">
                        <canvas #categoryApertureCanvas></canvas>
                      </div>
                    </mat-card-content>
                  </mat-card>
                }
                @if (categoryFocalData().length > 0) {
                  <mat-card>
                    <mat-card-header>
                      <mat-card-title>{{ 'stats.categories_focal_length' | translate }}</mat-card-title>
                    </mat-card-header>
                    <mat-card-content class="!pt-4">
                      <div [style.height.px]="categoryFocalData() | chartHeight">
                        <canvas #categoryFocalCanvas></canvas>
                      </div>
                    </mat-card-content>
                  </mat-card>
                }
              </div>

              <!-- Row 3: Gear table -->
              @if (categoryScoreProfile().length > 0) {
                <mat-card>
                  <mat-card-header>
                    <mat-card-title>{{ 'stats.categories_gear_profile' | translate }}</mat-card-title>
                  </mat-card-header>
                  <mat-card-content class="!pt-4 overflow-x-auto">
                    <table class="w-full text-sm">
                      <thead>
                        <tr class="text-gray-400 text-left border-b border-neutral-700">
                          <th class="pb-2 pr-4">{{ 'stats.categories.tab' | translate }}</th>
                          <th class="pb-2 pr-4">{{ 'stats.cameras' | translate }}</th>
                          <th class="pb-2 pr-4">{{ 'stats.lenses' | translate }}</th>
                          <th class="pb-2 pr-4">ISO</th>
                          <th class="pb-2 pr-4">f/</th>
                          <th class="pb-2">mm</th>
                        </tr>
                      </thead>
                      <tbody>
                        @for (cat of categoryScoreProfile(); track cat.category) {
                          <tr class="border-b border-neutral-800 hover:bg-neutral-800/30">
                            <td class="py-1.5 pr-4 font-medium">{{ ('category_names.' + cat.category) | translate }}</td>
                            <td class="py-1.5 pr-4 text-gray-300 truncate max-w-40">{{ cat.top_camera || '—' }}</td>
                            <td class="py-1.5 pr-4 text-gray-300 truncate max-w-40">{{ cat.top_lens || '—' }}</td>
                            <td class="py-1.5 pr-4 text-gray-300">{{ cat.avg_iso > 0 ? (cat.avg_iso | number:'1.0-0') : '—' }}</td>
                            <td class="py-1.5 pr-4 text-gray-300">{{ cat.avg_f_stop > 0 ? (cat.avg_f_stop | number:'1.1-1') : '—' }}</td>
                            <td class="py-1.5 text-gray-300">{{ cat.avg_focal_length > 0 ? (cat.avg_focal_length | number:'1.0-0') : '—' }}</td>
                          </tr>
                        }
                      </tbody>
                    </table>
                  </mat-card-content>
                </mat-card>
              }
            </div>
          </mat-tab>

          <!-- Score Distribution tab -->
          <mat-tab>
            <ng-template mat-tab-label>
              <mat-icon class="mr-2">bar_chart</mat-icon>
              {{ 'stats.score_distribution' | translate }}
            </ng-template>
            <div class="mt-4">
              <mat-card>
                <mat-card-header>
                  <mat-card-title>{{ 'stats.score_histogram' | translate }}</mat-card-title>
                </mat-card-header>
                <mat-card-content class="!pt-4">
                  @if (scoreLoading()) {
                    <div class="flex justify-center py-4"><mat-spinner diameter="32" /></div>
                  } @else {
                    <div class="h-80">
                      <canvas #scoreCanvas></canvas>
                    </div>
                  }
                </mat-card-content>
              </mat-card>
            </div>
          </mat-tab>

          <!-- Timeline tab -->
          <mat-tab>
            <ng-template mat-tab-label>
              <mat-icon class="mr-2">timeline</mat-icon>
              {{ 'stats.timeline' | translate }}
            </ng-template>
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
          </mat-tab>

          <!-- Correlations tab -->
          <mat-tab>
            <ng-template mat-tab-label>
              <mat-icon class="mr-2">insights</mat-icon>
              {{ 'stats.tabs.correlations' | translate }}
            </ng-template>
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
          </mat-tab>
        </mat-tab-group>
      }
    </div>
  `,
})
export class StatsComponent {
  private api = inject(ApiService);
  private i18n = inject(I18nService);
  private destroyRef = inject(DestroyRef);
  private route = inject(ActivatedRoute);
  private router = inject(Router);
  readonly statsFilters = inject(StatsFiltersService);
  private charts = new Map<string, Chart>();

  // Canvas refs
  protected readonly categoriesCanvas = viewChild<ElementRef<HTMLCanvasElement>>('categoriesCanvas');
  protected readonly scoreCanvas = viewChild<ElementRef<HTMLCanvasElement>>('scoreCanvas');
  protected readonly timelineCanvas = viewChild<ElementRef<HTMLCanvasElement>>('timelineCanvas');
  protected readonly yearlyCanvas = viewChild<ElementRef<HTMLCanvasElement>>('yearlyCanvas');

  protected readonly categoryScoreProfileCanvas = viewChild<ElementRef<HTMLCanvasElement>>('categoryScoreProfileCanvas');
  protected readonly categoryApertureCanvas = viewChild<ElementRef<HTMLCanvasElement>>('categoryApertureCanvas');
  protected readonly categoryFocalCanvas = viewChild<ElementRef<HTMLCanvasElement>>('categoryFocalCanvas');
  protected readonly dayOfWeekCanvas = viewChild<ElementRef<HTMLCanvasElement>>('dayOfWeekCanvas');
  protected readonly hourOfDayCanvas = viewChild<ElementRef<HTMLCanvasElement>>('hourOfDayCanvas');
  protected readonly correlationsCanvas = viewChild<ElementRef<HTMLCanvasElement>>('correlationsCanvas');
  selectedTab = signal(0);

  // Filter controls (shared with app header via StatsFiltersService)
  protected get dateFrom() { return this.statsFilters.dateFrom; }
  protected get dateTo() { return this.statsFilters.dateTo; }
  protected get filterCategory() { return this.statsFilters.filterCategory; }

  loading = signal(true);
  overview = signal<StatsOverview | null>(null);

  cameras = signal<GearItem[]>([]);
  lenses = signal<GearItem[]>([]);
  combos = signal<GearItem[]>([]);


  categoryScoreProfile = computed(() => [...this.categoryStats()].filter(c => c.avg_score > 0).sort((a, b) => b.avg_score - a.avg_score));
  categoryApertureProfile = computed(() => [...this.categoryStats()].filter(c => c.avg_f_stop > 0).sort((a, b) => a.avg_f_stop - b.avg_f_stop));
  categoryFocalData = computed(() => [...this.categoryStats()].filter(c => c.avg_focal_length > 0).sort((a, b) => a.avg_focal_length - b.avg_focal_length));
  gearLoading = signal(false);

  categoryStats = signal<CategoryStat[]>([]);
  categoriesLoading = signal(false);

  scoreBins = signal<ScoreBin[]>([]);
  scoreLoading = signal(false);

  timeline = signal<TimelineEntry[]>([]);
  yearlyData = signal<{ year: string; count: number }[]>([]);
  dayOfWeekData = signal<{ label: string; count: number }[]>([]);
  hourOfDayData = signal<{ label: string; count: number }[]>([]);
  heatmapGrid = signal<number[][]>([]); // [day 0-6][hour 0-23]
  private dayKeys = ['sun', 'mon', 'tue', 'wed', 'thu', 'fri', 'sat'];
  heatmapRows = computed(() => {
    return this.heatmapGrid().map((cells, i) => ({ day: this.i18n.t('stats.days.' + this.dayKeys[i]), cells }));
  });
  heatmapMax = signal(1);
  timelineLoading = signal(false);

  topCameras = signal<TopCamera[]>([]);

  // Correlation controls
  corrXAxis = signal('iso');
  corrYMetrics = signal<string[]>(['aggregate', 'aesthetic']);
  corrGroupBy = signal('');
  corrChartType = signal('line');
  corrMinSamples = signal(3);
  corrData = signal<CorrelationApiResponse | null>(null);
  corrBucketCount = computed(() => this.corrData()?.labels?.length ?? 0);
  correlationLoading = signal(false);

  corrDimensions = [
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
  corrMetricOptions = [
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
  corrChartTypes = [
    { key: 'line' }, { key: 'area' }, { key: 'bar' }, { key: 'horizontalBar' },
  ];

  constructor() {
    // Initialize filters from URL
    const params = this.route.snapshot.queryParams;
    if (params['category']) this.statsFilters.filterCategory.set(params['category']);
    if (params['date_from']) this.statsFilters.dateFrom.set(params['date_from']);
    if (params['date_to']) this.statsFilters.dateTo.set(params['date_to']);

    // Sync signals to URL
    effect(() => {
      const cat = this.statsFilters.filterCategory();
      const from = this.statsFilters.dateFrom();
      const to = this.statsFilters.dateTo();
      
      const qp: any = {};
      if (cat) qp.category = cat;
      if (from) qp.date_from = from;
      if (to) qp.date_to = to;
      
      this.router.navigate([], { 
        queryParams: qp, 
        queryParamsHandling: 'merge', 
        replaceUrl: true 
      });
    });

    // Reload when filter signals change (from header or local filter bar)
    effect(() => {
      this.statsFilters.filterCategory();
      this.statsFilters.dateFrom();
      this.statsFilters.dateTo();
      this.loadAll();
    });

    // Destroy Chart.js instances on component teardown
    this.destroyRef.onDestroy(() => {
      this.charts.forEach(chart => chart.destroy());
      this.charts.clear();
    });

    // Chart effects — rebuild when data or canvas changes
    effect(() => {
      const cats = this.categoryStats();
      this.buildHorizontalBar('categories', this.categoriesCanvas(), cats.map(c => this.translateCategory(c.category)), cats.map(c => c.count), COLORS[0]);
    });
    effect(() => {
      const bins = this.scoreBins();
      this.buildVerticalBar('score', this.scoreCanvas(), bins.map(b => b.range), bins.map(b => b.count), COLORS[1]);
    });
    effect(() => {
      const data = this.timeline();
      this.buildAreaLine('timeline', this.timelineCanvas(), data.map(t => t.period), data.map(t => t.count), COLORS[0]);
    });
    effect(() => {
      const data = this.yearlyData();
      this.buildVerticalBar('yearly', this.yearlyCanvas(), data.map(y => y.year), data.map(y => y.count), COLORS[0]);
    });
    effect(() => {
      const data = this.dayOfWeekData();
      this.buildVerticalBar('dayOfWeek', this.dayOfWeekCanvas(), data.map(d => d.label), data.map(d => d.count), COLORS[2]);
    });
    effect(() => {
      const data = this.hourOfDayData();
      this.buildVerticalBar('hourOfDay', this.hourOfDayCanvas(), data.map(d => d.label), data.map(d => d.count), COLORS[5]);
    });

    // Score profile (grouped: aggregate + aesthetic + composition + sharpness + color)
    effect(() => {
      const cats = this.categoryScoreProfile();
      const labels = cats.map(c => this.translateCategory(c.category));
      this.buildGroupedHorizontalBar('categoryScoreProfile', this.categoryScoreProfileCanvas(), labels, [
        { label: this.i18n.t('stats.axes.aggregate'),    data: cats.map(c => c.avg_score),        color: COLORS[3] },
        { label: this.i18n.t('stats.axes.aesthetic'),    data: cats.map(c => c.avg_aesthetic),    color: COLORS[0] },
        { label: this.i18n.t('stats.axes.composition'),  data: cats.map(c => c.avg_composition),  color: COLORS[1] },
        { label: this.i18n.t('stats.axes.sharpness'),    data: cats.map(c => c.avg_sharpness),    color: COLORS[2] },
        { label: this.i18n.t('stats.axes.color'),        data: cats.map(c => c.avg_color),        color: COLORS[5] },
        { label: this.i18n.t('stats.axes.exposure'),     data: cats.map(c => c.avg_exposure),     color: COLORS[4] },
        { label: this.i18n.t('stats.axes.face_quality'), data: cats.map(c => c.avg_face_quality), color: COLORS[6] },
        { label: this.i18n.t('stats.axes.contrast'),     data: cats.map(c => c.avg_contrast),     color: COLORS[7] },
      ]);
    });
    // Aperture by category
    effect(() => {
      const cats = this.categoryApertureProfile();
      this.buildHorizontalBar('categoryAperture', this.categoryApertureCanvas(),
        cats.map(c => this.translateCategory(c.category)), cats.map(c => c.avg_f_stop), COLORS[2]);
    });
    // Focal length by category
    effect(() => {
      const cats = this.categoryFocalData();
      this.buildHorizontalBar('categoryFocal', this.categoryFocalCanvas(),
        cats.map(c => this.translateCategory(c.category)), cats.map(c => c.avg_focal_length), COLORS[6]);
    });
    effect(() => {
      const data = this.corrData();
      if (data) {
        this.buildCorrelationChart(data);
      }
    });
  }

  private get filterParams(): Record<string, string> {
    const params: Record<string, string> = {};
    if (this.dateFrom()) params['date_from'] = this.dateFrom();
    if (this.dateTo()) params['date_to'] = this.dateTo();
    if (this.filterCategory()) params['category'] = this.filterCategory();
    return params;
  }

  // --- Data Loading ---

  async loadAll(): Promise<void> {
    this.loading.set(true);
    try {
      const overview = await firstValueFrom(this.api.get<StatsOverview>('/stats/overview', this.filterParams));
      this.overview.set(overview);
    } catch { /* empty */ }
    finally { this.loading.set(false); }

    this.loadGear();
    this.loadCategories();
    this.loadScoreDistribution();
    this.loadTimeline();
    this.loadTopCameras();
  }

  private mapGearItem(r: Record<string, unknown>): GearItem {
    return {
      name: r['name'] as string, count: r['count'] as number,
      avg_score: (r['avg_aggregate'] as number) ?? 0,
      avg_aesthetic: (r['avg_aesthetic'] as number) ?? 0,
      avg_sharpness: (r['avg_sharpness'] as number) ?? 0,
      avg_composition: (r['avg_composition'] as number) ?? 0,
      avg_exposure: (r['avg_exposure'] as number) ?? 0,
      avg_color: (r['avg_color'] as number) ?? 0,
      avg_iso: (r['avg_iso'] as number) ?? 0,
      avg_f_stop: (r['avg_f_stop'] as number) ?? 0,
      avg_focal_length: (r['avg_focal_length'] as number) ?? 0,
      avg_face_count: (r['avg_face_count'] as number) ?? 0,
      avg_monochrome: (r['avg_monochrome'] as number) ?? 0,
      avg_dynamic_range: (r['avg_dynamic_range'] as number) ?? 0,
      history: (r['history'] as { date: string; count: number }[]) ?? [],
    };
  }

  async loadGear(): Promise<void> {
    this.gearLoading.set(true);
    try {
      const data = await firstValueFrom(this.api.get<GearApiResponse>('/stats/gear', this.filterParams));
      this.cameras.set((data.cameras ?? []).map(c => this.mapGearItem(c as unknown as Record<string, unknown>)));
      this.lenses.set((data.lenses ?? []).map(l => this.mapGearItem(l as unknown as Record<string, unknown>)));
      this.combos.set((data.combos ?? []).map(c => this.mapGearItem(c as unknown as Record<string, unknown>)));
    } catch { /* empty */ }
    finally { this.gearLoading.set(false); }
  }

  async loadCategories(): Promise<void> {
    this.categoriesLoading.set(true);
    try {
      const data = await firstValueFrom(this.api.get<CategoryStat[]>('/stats/categories', this.filterParams));
      this.categoryStats.set(data);
    } catch { /* empty */ }
    finally { this.categoriesLoading.set(false); }
  }

  async loadScoreDistribution(): Promise<void> {
    this.scoreLoading.set(true);
    try {
      const data = await firstValueFrom(this.api.get<ScoreBin[]>('/stats/score_distribution', this.filterParams));
      this.scoreBins.set(data);
    } catch { /* empty */ }
    finally { this.scoreLoading.set(false); }
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

      // Parse heatmap into day-of-week and hour-of-day aggregations
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

        // Build 7x24 grid for heatmap
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

  async loadTopCameras(): Promise<void> {
    try {
      const data = await firstValueFrom(this.api.get<TopCamera[]>('/stats/top_cameras', this.filterParams));
      this.topCameras.set(data);
    } catch { /* empty */ }
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

  // --- Helpers ---

  private translateCategory(name: string): string {
    const key = `category_names.${name}`;
    const translated = this.i18n.t(key);
    return translated === key ? name : translated;
  }

  // --- Chart Builders ---

  private buildHorizontalBar(id: string, ref: ElementRef<HTMLCanvasElement> | undefined, labels: string[], data: number[], color: string): void {
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
    }));
  }

  private buildGroupedHorizontalBar(
    id: string,
    ref: ElementRef<HTMLCanvasElement> | undefined,
    labels: string[],
    datasets: { label: string; data: number[]; color: string }[],
  ): void {
    if (!ref || labels.length === 0) return;
    this.destroyChart(id);
    const ctx = ref.nativeElement.getContext('2d');
    if (!ctx) return;
    this.charts.set(id, new Chart(ctx, {
      type: 'bar',
      data: {
        labels,
        datasets: datasets.map(d => ({
          label: d.label,
          data: d.data,
          backgroundColor: d.color + 'bb',
          borderColor: d.color,
          borderWidth: 1,
          borderRadius: 2,
        })),
      },
      options: {
        indexAxis: 'y',
        responsive: true,
        maintainAspectRatio: false,
        plugins: {
          legend: { display: true, position: 'top', labels: { color: '#a3a3a3', boxWidth: 12 } },
          tooltip: { callbacks: { label: (ctx) => `${ctx.dataset.label}: ${(ctx.parsed.x ?? 0).toFixed(2)}` } },
        },
        scales: {
          x: { grid: { color: '#262626' }, ticks: { color: '#a3a3a3' }, min: 0, max: 10 },
          y: { grid: { display: false }, ticks: { color: '#d4d4d4', font: { size: 11 } } },
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

  private buildCorrelationChart(apiData: CorrelationApiResponse): void {
    const ref = this.correlationsCanvas();
    if (!ref || !apiData.labels?.length) return;
    this.destroyChart('correlations');
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

    if (apiData.groups && Object.keys(apiData.groups).length > 0) {
      // Grouped mode
      const groupNames = Object.keys(apiData.groups);
      for (let gi = 0; gi < groupNames.length; gi++) {
        const grp = groupNames[gi];
        const color = COLORS[gi % COLORS.length];
        // For grouped data, take first y metric's values
        const yMetric = this.corrYMetrics()[0] ?? 'aggregate';
        const data = labels.map(lbl => apiData.groups![grp]?.[lbl]?.[yMetric] ?? null);
        datasets.push({
          label: grp,
          data,
          backgroundColor: color + (type === 'bar' ? 'cc' : '33'),
          borderColor: color,
          borderWidth: type === 'bar' ? 1 : 2,
          fill: fill,
          tension: type === 'line' ? 0.3 : undefined,
          pointRadius: type === 'line' ? 2 : undefined,
          borderRadius: type === 'bar' ? 3 : undefined,
        });
      }
    } else if (apiData.metrics) {
      // Non-grouped mode — one dataset per metric
      const metricNames = Object.keys(apiData.metrics);
      for (let mi = 0; mi < metricNames.length; mi++) {
        const metric = metricNames[mi];
        const color = COLORS[mi % COLORS.length];
        const values = apiData.metrics[metric] ?? [];
        datasets.push({
          label: metric,
          data: values,
          backgroundColor: color + (type === 'bar' ? 'cc' : '33'),
          borderColor: color,
          borderWidth: type === 'bar' ? 1 : 2,
          fill: fill,
          tension: type === 'line' ? 0.3 : undefined,
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
          x: { grid: { color: '#262626' }, ticks: { color: '#a3a3a3', maxRotation: 45, autoSkip: true } },
          y: { grid: { color: '#262626' }, ticks: { color: '#a3a3a3' } },
        },
      },
    }));
  }

  readonly hours = Array.from({ length: 24 }, (_, i) => i);

  private destroyChart(id: string): void {
    const existing = this.charts.get(id);
    if (existing) {
      existing.destroy();
      this.charts.delete(id);
    }
  }

}
