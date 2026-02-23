import { Component, inject, signal, computed, viewChild, ElementRef, effect, DestroyRef } from '@angular/core';
import { DecimalPipe } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { MatCardModule } from '@angular/material/card';
import { MatTabsModule } from '@angular/material/tabs';
import { MatIconModule } from '@angular/material/icon';
import { MatButtonModule } from '@angular/material/button';
import { MatProgressSpinnerModule } from '@angular/material/progress-spinner';
import { firstValueFrom } from 'rxjs';
import { Router, ActivatedRoute } from '@angular/router';
import { Chart, registerables } from 'chart.js';
import { ApiService } from '../../core/services/api.service';
import { I18nService } from '../../core/services/i18n.service';
import { TranslatePipe } from '../../shared/pipes/translate.pipe';
import { StatsFiltersService } from './stats-filters.service';
import { GearChartCardComponent, GearItem } from './gear-chart-card.component';
import { ChartHeightPipe } from './chart-height.pipe';
import { StatsTimelineTabComponent } from './stats-timeline-tab.component';
import { StatsCorrelationsTabComponent } from './stats-correlations-tab.component';

Chart.register(...registerables);
Chart.defaults.color = '#a3a3a3';
Chart.defaults.borderColor = '#262626';

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

interface TopCamera {
  name: string;
  count: number;
  avg_score: number;
  avg_aesthetic: number;
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
    TranslatePipe,
    ChartHeightPipe,
    GearChartCardComponent,
    StatsTimelineTabComponent,
    StatsCorrelationsTabComponent,
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
              <app-gear-chart-card titleKey="stats.cameras" [items]="cameras()" [loading]="gearLoading()" color="#22c55e" />
              <app-gear-chart-card titleKey="stats.lenses" [items]="lenses()" [loading]="gearLoading()" color="#3b82f6" />
              @if (combos().length > 0) {
                <app-gear-chart-card titleKey="stats.charts.camera_lens_combos" [items]="combos()" [loading]="gearLoading()" color="#f59e0b" />
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
            <app-stats-timeline-tab />
          </mat-tab>

          <!-- Correlations tab -->
          <mat-tab>
            <ng-template mat-tab-label>
              <mat-icon class="mr-2">insights</mat-icon>
              {{ 'stats.tabs.correlations' | translate }}
            </ng-template>
            <app-stats-correlations-tab />
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
  protected readonly categoryScoreProfileCanvas = viewChild<ElementRef<HTMLCanvasElement>>('categoryScoreProfileCanvas');
  protected readonly categoryApertureCanvas = viewChild<ElementRef<HTMLCanvasElement>>('categoryApertureCanvas');
  protected readonly categoryFocalCanvas = viewChild<ElementRef<HTMLCanvasElement>>('categoryFocalCanvas');

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
  gearLoading = signal(false);

  categoryStats = signal<CategoryStat[]>([]);
  categoriesLoading = signal(false);

  categoryScoreProfile = computed(() => [...this.categoryStats()].filter(c => c.avg_score > 0).sort((a, b) => b.avg_score - a.avg_score));
  categoryApertureProfile = computed(() => [...this.categoryStats()].filter(c => c.avg_f_stop > 0).sort((a, b) => a.avg_f_stop - b.avg_f_stop));
  categoryFocalData = computed(() => [...this.categoryStats()].filter(c => c.avg_focal_length > 0).sort((a, b) => a.avg_focal_length - b.avg_focal_length));

  scoreBins = signal<ScoreBin[]>([]);
  scoreLoading = signal(false);

  topCameras = signal<TopCamera[]>([]);

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
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      const qp: any = {};
      if (cat) qp.category = cat;
      if (from) qp.date_from = from;
      if (to) qp.date_to = to;
      this.router.navigate([], { queryParams: qp, queryParamsHandling: 'merge', replaceUrl: true });
    });

    // Reload when filter signals change
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

    // Chart effects
    effect(() => {
      const cats = this.categoryStats();
      this.buildHorizontalBar('categories', this.categoriesCanvas(), cats.map(c => this.translateCategory(c.category)), cats.map(c => c.count), COLORS[0]);
    });
    effect(() => {
      const bins = this.scoreBins();
      this.buildVerticalBar('score', this.scoreCanvas(), bins.map(b => b.range), bins.map(b => b.count), COLORS[1]);
    });
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
    effect(() => {
      const cats = this.categoryApertureProfile();
      this.buildHorizontalBar('categoryAperture', this.categoryApertureCanvas(),
        cats.map(c => this.translateCategory(c.category)), cats.map(c => c.avg_f_stop), COLORS[2]);
    });
    effect(() => {
      const cats = this.categoryFocalData();
      this.buildHorizontalBar('categoryFocal', this.categoryFocalCanvas(),
        cats.map(c => this.translateCategory(c.category)), cats.map(c => c.avg_focal_length), COLORS[6]);
    });
  }

  private get filterParams(): Record<string, string> {
    const params: Record<string, string> = {};
    if (this.dateFrom()) params['date_from'] = this.dateFrom();
    if (this.dateTo()) params['date_to'] = this.dateTo();
    if (this.filterCategory()) params['category'] = this.filterCategory();
    return params;
  }

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

  async loadTopCameras(): Promise<void> {
    try {
      const data = await firstValueFrom(this.api.get<TopCamera[]>('/stats/top_cameras', this.filterParams));
      this.topCameras.set(data);
    } catch { /* empty */ }
  }

  private translateCategory(name: string): string {
    const key = `category_names.${name}`;
    const translated = this.i18n.t(key);
    return translated === key ? name : translated;
  }

  private buildHorizontalBar(id: string, ref: ElementRef<HTMLCanvasElement> | undefined, labels: string[], data: number[], color: string): void {
    if (!ref || data.length === 0) return;
    this.destroyChart(id);
    const ctx = ref.nativeElement.getContext('2d');
    if (!ctx) return;
    this.charts.set(id, new Chart(ctx, {
      type: 'bar',
      data: {
        labels,
        datasets: [{ data, backgroundColor: color + 'cc', borderColor: color, borderWidth: 1, borderRadius: 2 }],
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
          label: d.label, data: d.data,
          backgroundColor: d.color + 'bb', borderColor: d.color, borderWidth: 1, borderRadius: 2,
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
        datasets: [{ data, backgroundColor: color + 'cc', borderColor: color, borderWidth: 1, borderRadius: 3 }],
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
