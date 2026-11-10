import { COMPACT_PAGE_TABS, TabLabelComponent } from '../../shared/components/tab-label/tab-label.component';
import { Component, inject, signal, computed, viewChild, ElementRef, effect, DestroyRef, Injector, afterNextRender, untracked, ChangeDetectionStrategy, TemplateRef } from '@angular/core';
import { DOCUMENT, NgTemplateOutlet } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { MatCardModule } from '@angular/material/card';
import { MatTabsModule } from '@angular/material/tabs';
import { MatIconModule } from '@angular/material/icon';
import { MatButtonModule } from '@angular/material/button';
import { MatFormFieldModule } from '@angular/material/form-field';
import { MatSelectModule } from '@angular/material/select';
import { MatProgressSpinnerModule } from '@angular/material/progress-spinner';
import { MatTooltipModule } from '@angular/material/tooltip';
import { firstValueFrom } from 'rxjs';
import { Router, ActivatedRoute } from '@angular/router';
import { Chart, registerables } from 'chart.js';
import { ApiService } from '../../core/services/api.service';
import { AuthService } from '../../core/services/auth.service';
import { HttpContext } from '@angular/common/http';
import { HANDLE_SERVER_ERROR_LOCALLY } from '../../core/utils/http-error-context';
import { I18nService } from '../../core/services/i18n.service';
import { TranslatePipe } from '../../shared/pipes/translate.pipe';
import { ThemeService } from '../../core/services/theme.service';
import { HeaderSlotService } from '../../core/services/header-slot.service';
import { SortOptionIconPipe } from '../../shared/pipes/sort-option-icon.pipe';
import { PageHelpService } from '../../core/services/page-help.service';
import { DateRangeFilterComponent } from '../../shared/components/date-range-filter/date-range-filter.component';
import { GalleryStore } from '../gallery/gallery.store';
import { StatsFiltersService, StatsOverviewData } from './stats-filters.service';
import { registerPageContext } from '../../core/agent/page-context.service';
import { GearChartCardComponent, GearItem } from './gear-chart-card.component';
import { ChartHeightPipe } from './chart-height.pipe';
import { chartTheme, chartSeriesColor, chartSeriesColors } from './chart-theme';
import { StatsTimelineTabComponent } from './stats-timeline-tab.component';
import { StatsCorrelationsTabComponent } from './stats-correlations-tab.component';
import { StatsNumberPipe } from './stats-locale-number.pipe';
import { statsAuthScope } from './stats-auth-scope';
import { downloadCsv } from '../../shared/utils/csv';
import { I18N, i18nKeys } from '../../core/i18n/keys';
import { SelectTriggerLabelComponent } from '../../shared/components/select-trigger-label/select-trigger-label.component';

Chart.register(...registerables);

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

type ProfileField = 'avg_score' | 'avg_aesthetic' | 'avg_composition' | 'avg_sharpness' | 'avg_color' | 'avg_exposure' | 'avg_face_quality' | 'avg_contrast';

interface ScoreBin {
  range: string;
  min: number;
  max: number;
  count: number;
  percentage: number;
}

@Component({
  selector: 'app-stats',
  imports: [
    SelectTriggerLabelComponent,
    NgTemplateOutlet,
    TabLabelComponent,
    StatsNumberPipe,
    FormsModule,
    MatCardModule,
    MatTabsModule,
    MatIconModule,
    MatButtonModule,
    MatFormFieldModule,
    MatSelectModule,
    MatProgressSpinnerModule,
    MatTooltipModule,
    TranslatePipe,
    SortOptionIconPipe,
    DateRangeFilterComponent,
    ChartHeightPipe,
    GearChartCardComponent,
    StatsTimelineTabComponent,
    StatsCorrelationsTabComponent,
  ],
  host: { class: 'block px-4 py-4 [&_mat-card]:border [&_mat-card]:border-[var(--mat-sys-outline-variant)]' },
  changeDetection: ChangeDetectionStrategy.Eager,
  template: `
    <h1 id="stats-heading" tabindex="-1" class="sr-only">{{ I18N.nav.stats | translate }}</h1>
    <!-- Page actions: lg+ renders this in the shell's page-actions bar (HeaderSlotService); below lg the
         in-page header further down carries the counts and the collapsible filters instead. The counts
         move into the page from lg up to xl, where the bar has no room for them beside the filters. -->
    <ng-template #statsToolbar>
      <mat-form-field class="w-52 shrink-0" subscriptSizing="dynamic">
        <mat-label>{{ I18N.ui.filters.type | translate }}</mat-label>
        <mat-select panelWidth="auto" panelClass="nowrap-panel" [value]="statsFilters.filterCategory()" (selectionChange)="onStatsCategoryChange($event.value)">
          <mat-option value="">{{ I18N.gallery.all_photos | translate }}</mat-option>
          @if (unknownCategory(); as category) {
            <mat-option [value]="category">{{ unknownCategoryLabel() }}</mat-option>
          }
          @for (t of store.types(); track t.id) {
            <mat-option [value]="t.id">{{ (t.id === 'top_picks' ? 'photo_types.top_picks' : 'category_names.' + t.id) | translate }} ({{ t.count }})</mat-option>
          }
        </mat-select>
      </mat-form-field>
      <app-date-range-filter
        [from]="statsFilters.dateFrom()" [to]="statsFilters.dateTo()"
        fromLabel="stats.filter.date_from" toLabel="stats.filter.date_to"
        fromClass="w-44 shrink-0" toClass="w-44 shrink-0"
        (fromChange)="statsFilters.dateFrom.set($event)" (toChange)="statsFilters.dateTo.set($event)" />
      @if (statsFilters.overview(); as overview) {
        <dl class="m-0 ml-auto hidden xl:flex shrink-0 items-baseline gap-x-5 whitespace-nowrap text-sm tabular-nums" data-stats-overview-bar>
          <div class="flex items-baseline gap-1.5">
            <dt class="text-[var(--mat-sys-on-surface-variant)]">{{ I18N.stats.total_photos | translate }}</dt>
            <dd class="m-0 font-semibold">{{ overview.total_photos | statsNumber:i18n.locale() }}</dd>
          </div>
          <div class="flex items-baseline gap-1.5">
            <dt class="text-[var(--mat-sys-on-surface-variant)]">{{ I18N.stats.total_persons | translate }}</dt>
            <dd class="m-0 font-semibold">{{ overview.total_persons | statsNumber:i18n.locale() }}</dd>
          </div>
          <div class="flex items-baseline gap-1.5">
            <dt class="text-[var(--mat-sys-on-surface-variant)]">{{ I18N.stats.avg_score | translate }}</dt>
            <dd class="m-0 font-semibold">{{ overview.total_photos ? (overview.avg_score | statsNumber:i18n.locale():1) : '—' }}</dd>
          </div>
          <div class="flex items-baseline gap-1.5">
            <dt class="text-[var(--mat-sys-on-surface-variant)]">{{ I18N.stats.total_faces | translate }}</dt>
            <dd class="m-0 font-semibold">{{ overview.total_faces | statsNumber:i18n.locale() }}</dd>
          </div>
        </dl>
      }
    </ng-template>
    <header class="mb-4 space-y-2 border-b border-[var(--mat-sys-outline-variant)] pb-3 sm:space-y-4 sm:pb-4 xl:hidden">
      @if (statsFilters.overview(); as overview) {
        <dl class="m-0 grid grid-cols-2 gap-x-3 gap-y-1 rounded-lg bg-[var(--mat-sys-surface-container-low)] px-2 py-1.5 text-sm sm:flex sm:flex-wrap sm:gap-x-5 sm:bg-transparent sm:p-0" data-stats-overview>
          <div class="flex min-w-0 items-baseline gap-1.5">
            <dt class="text-[var(--mat-sys-on-surface-variant)]">{{ I18N.stats.total_photos | translate }}</dt>
            <dd class="m-0 font-semibold tabular-nums">{{ overview.total_photos | statsNumber:i18n.locale() }}</dd>
          </div>
          <div class="flex min-w-0 items-baseline gap-1.5">
            <dt class="text-[var(--mat-sys-on-surface-variant)]">{{ I18N.stats.total_persons | translate }}</dt>
            <dd class="m-0 font-semibold tabular-nums">{{ overview.total_persons | statsNumber:i18n.locale() }}</dd>
          </div>
          <div class="flex min-w-0 items-baseline gap-1.5">
            <dt class="text-[var(--mat-sys-on-surface-variant)]">{{ I18N.stats.avg_score | translate }}</dt>
            <dd class="m-0 font-semibold tabular-nums">{{ overview.total_photos ? (overview.avg_score | statsNumber:i18n.locale():1) : '—' }}</dd>
          </div>
          <div class="flex min-w-0 items-baseline gap-1.5">
            <dt class="text-[var(--mat-sys-on-surface-variant)]">{{ I18N.stats.total_faces | translate }}</dt>
            <dd class="m-0 font-semibold tabular-nums">{{ overview.total_faces | statsNumber:i18n.locale() }}</dd>
          </div>
        </dl>
      }
      <details class="group lg:hidden">
        <summary class="flex min-h-11 cursor-pointer flex-wrap items-center gap-2 py-1 text-sm font-medium text-[var(--mat-sys-primary)]">
          <mat-icon aria-hidden="true">filter_list</mat-icon>{{ I18N.ui.buttons.filters | translate }}
          @if (statsFilters.filterCategory() || statsFilters.dateFrom() || statsFilters.dateTo()) {
            <span class="h-2 w-2 rounded-full bg-[var(--mat-sys-primary)]" aria-hidden="true"></span>
            <span class="order-last min-w-0 basis-full break-words font-normal text-[var(--mat-sys-on-surface-variant)]">{{ filterSummary() }}</span>
          }
          <mat-icon aria-hidden="true" class="transition-transform group-open:rotate-180">expand_more</mat-icon>
        </summary>
        <ng-container [ngTemplateOutlet]="statsFiltersTemplate" />
      </details>
      <ng-template #statsFiltersTemplate>
      <div class="grid grid-cols-2 gap-2 sm:grid-cols-3" data-stats-filters>
      <mat-form-field class="col-span-2 min-w-0 sm:col-span-1" subscriptSizing="dynamic">
        <mat-label>{{ I18N.ui.filters.type | translate }}</mat-label>
        <mat-select panelWidth="auto" panelClass="nowrap-panel" [value]="statsFilters.filterCategory()" (selectionChange)="onStatsCategoryChange($event.value)">
          <mat-option value="">{{ I18N.gallery.all_photos | translate }}</mat-option>
          @if (unknownCategory(); as category) {
            <mat-option [value]="category">{{ unknownCategoryLabel() }}</mat-option>
          }
          @for (t of store.types(); track t.id) {
            <mat-option [value]="t.id">{{ (t.id === 'top_picks' ? 'photo_types.top_picks' : 'category_names.' + t.id) | translate }} ({{ t.count }})</mat-option>
          }
        </mat-select>
      </mat-form-field>
      <app-date-range-filter
        [from]="statsFilters.dateFrom()" [to]="statsFilters.dateTo()"
        fromLabel="stats.filter.date_from" toLabel="stats.filter.date_to"
        fromClass="min-w-0 w-full"
        (fromChange)="statsFilters.dateFrom.set($event)" (toChange)="statsFilters.dateTo.set($event)" />
      </div>
      </ng-template>
    </header>
    @if (loadFailed() || retrying()) {
      <div role="alert" class="mb-4 flex flex-wrap items-center gap-3 rounded-lg bg-[var(--mat-sys-error-container)] p-3 text-[var(--mat-sys-on-error-container)]">
        <span>{{ (retrying() ? I18N.ui.labels.loading : I18N.stats.correlations.error) | translate }}</span>
        <button mat-stroked-button data-stats-retry class="min-h-11" [attr.aria-disabled]="retrying()" (click)="retryLoad()">{{ (retrying() ? I18N.ui.labels.loading : I18N.gallery.load_error.retry) | translate }}</button>
      </div>
    }
    <ng-template #sectionError let-section>
      <div role="alert" class="mt-4 flex flex-wrap items-center gap-3 rounded-lg bg-[var(--mat-sys-error-container)] p-3 text-[var(--mat-sys-on-error-container)]">
        <span>{{ I18N.stats.correlations.error | translate }}</span>
        <button mat-stroked-button class="min-h-11" (click)="retrySection(section)">{{ I18N.gallery.load_error.retry | translate }}</button>
      </div>
    </ng-template>
    @if (loading()) {
      <div class="flex justify-center py-16">
        <mat-spinner diameter="48" [attr.aria-label]="I18N.ui.labels.loading | translate" />
      </div>
    } @else if (!loadFailed()) {
      <mat-tab-group class="page-tabs" [class]="compactTabs" mat-stretch-tabs="false" mat-align-tabs="start" [selectedIndex]="selectedTab()" (selectedIndexChange)="selectedTab.set($event)">
          <!-- Gear tab -->
          <mat-tab>
            <ng-template mat-tab-label>
              <app-tab-label icon="camera_alt" [label]="I18N.stats.gear | translate" />
            </ng-template>
            @if (gearFailed()) {
              <ng-container *ngTemplateOutlet="sectionError; context: { $implicit: 'gear' }" />
            }
            <div class="grid grid-cols-1 xl:grid-cols-2 gap-4 mt-4">
              <app-gear-chart-card titleKey="stats.cameras" [items]="cameras()" [loading]="gearLoading()" [color]="themeService.accentColor()" />
              <app-gear-chart-card titleKey="stats.lenses" [items]="lenses()" [loading]="gearLoading()" [color]="themeService.complementaryColor()" />
              @if (combos().length > 0) {
                <!-- Spans the bottom row: two top cards + one full-width combo
                     chart beat a 3-column grid that strands a blank cell
                     whenever the combos chart is the only third card. -->
                <div class="xl:col-span-2">
                  <app-gear-chart-card titleKey="stats.charts.camera_lens_combos" [items]="combos()" [loading]="gearLoading()" [color]="themeService.accentColor()" />
                </div>
              }
            </div>
          </mat-tab>

          <!-- Categories tab -->
          <mat-tab>
            <ng-template mat-tab-label>
              <app-tab-label icon="category" [label]="I18N.stats.categories.tab | translate" />
            </ng-template>
            @if (categoriesFailed()) {
              <ng-container *ngTemplateOutlet="sectionError; context: { $implicit: 'categories' }" />
            }
            <div class="mt-4 flex flex-col gap-4">
              <div class="grid grid-cols-1 lg:grid-cols-2 2xl:grid-cols-3 items-start gap-4">
                @if (categoryMetricData().length > 0) {
                  <mat-card>
                    <mat-card-header class="!flex !flex-wrap !items-center !justify-between !gap-x-4 !gap-y-2">
                      <h2 mat-card-title>{{ I18N.stats.category_metric_title | translate }}</h2>
                      <mat-form-field class="min-w-40 flex-1" subscriptSizing="dynamic">
                        <mat-label>{{ I18N.stats.gear_metric_label | translate }}</mat-label>
                        <mat-select [ngModel]="categoryMetric()" (ngModelChange)="categoryMetric.set($event)">
                          <mat-select-trigger>
                            @let metricIcon = categoryMetric() | sortOptionIcon;
                            <app-select-trigger-label [icon]="metricIcon">{{ 'stats.category_metrics.' + categoryMetric() | translate }}</app-select-trigger-label>
                          </mat-select-trigger>
                          @for (opt of categoryMetricOptions; track opt.key) {
                            @let optionIcon = opt.key | sortOptionIcon;
                            <mat-option [value]="opt.key">
                              <mat-icon aria-hidden="true" class="!w-8 text-center" [class]="optionIcon.classes">{{ optionIcon.text }}</mat-icon>
                              {{ 'stats.category_metrics.' + opt.key | translate }}
                            </mat-option>
                          }
                        </mat-select>
                      </mat-form-field>
                    </mat-card-header>
                    <mat-card-content class="!pt-4">
                      <div [style.height.px]="categoryMetricData() | chartHeight">
                        <canvas #categoryMetricCanvas role="img" [attr.aria-label]="I18N.stats.category_metric_title | translate"></canvas>
                      </div>
                      <details class="mt-2 text-sm">
                        <summary class="min-h-11 cursor-pointer content-center text-[var(--mat-sys-primary)]">{{ I18N.stats.show_chart_data | translate }}</summary>
                        <table class="w-full border-collapse text-left">
                          <caption class="sr-only">{{ I18N.stats.category_metric_title | translate }}</caption>
                          <thead><tr><th scope="col" class="py-1 pr-4">{{ I18N.stats.categories.tab | translate }}</th><th scope="col" class="py-1 text-right">{{ ('stats.category_metrics.' + categoryMetric()) | translate }}</th></tr></thead>
                          <tbody>
                            @for (row of categoryMetricRows(); track row.category) {
                              <tr><th scope="row" class="py-1 pr-4 text-left font-medium">{{ row.label }}</th><td class="py-1 text-right tabular-nums">{{ row.value | statsNumber:i18n.locale():categoryMetricDigits() }}</td></tr>
                            }
                          </tbody>
                        </table>
                      </details>
                    </mat-card-content>
                  </mat-card>
                }

                @if (categoryScoreProfile().length > 0) {
                  <mat-card class="lg:col-span-2 2xl:col-span-3">
                    <mat-card-header class="!flex !flex-wrap !items-center !justify-between !gap-3">
                      <h2 mat-card-title class="shrink-0">{{ I18N.stats.categories_score_profile | translate }}</h2>
                      <mat-form-field class="flex-1 min-w-[10rem] !-mt-2 max-sm:order-last max-sm:basis-full" subscriptSizing="dynamic">
                        <!-- No mat-label, as on the gear cards: the card title names the chart. -->
                        <mat-select multiple data-profile-series [value]="profileSeries()" (selectionChange)="onProfileSeriesChange($event.value)"
                                    [aria-label]="I18N.stats.profile_series | translate">
                          <mat-select-trigger>
                            @if (profileSeriesSummary(); as summary) {
                              {{ summary }}
                            } @else {
                              <span class="inline-flex items-center gap-1.5 align-middle">
                                @for (def of selectedProfileDefs(); track def.key) {
                                  <span class="inline-block h-3 w-3 rounded-sm" [style.background-color]="profileColors()[def.colorIndex]"></span>
                                }
                              </span>
                            }
                          </mat-select-trigger>
                          @for (def of profileSeriesDefs; track def.key) {
                            @let seriesIcon = def.key | sortOptionIcon;
                            <mat-option [value]="def.key">
                              <span class="inline-flex items-center gap-2">
                                <span class="inline-block h-3 w-3 shrink-0 rounded-sm" [style.background-color]="profileColors()[def.colorIndex]" aria-hidden="true"></span>
                                <mat-icon aria-hidden="true" class="!w-8 text-center" [class]="seriesIcon.classes">{{ seriesIcon.text }}</mat-icon>
                                {{ def.labelKey | translate }}
                              </span>
                            </mat-option>
                          }
                        </mat-select>
                      </mat-form-field>
                    </mat-card-header>
                    <mat-card-content class="!pt-4">
                      @if (categoriesLoading()) {
                        <div class="flex justify-center py-4"><mat-spinner diameter="32" [attr.aria-label]="I18N.ui.labels.loading | translate" /></div>
                      } @else {
                        <div class="max-h-[70vh] overflow-y-auto">
                          <div [style.height.px]="categoryScoreProfile() | chartHeight:80">
                            <canvas #categoryScoreProfileCanvas role="img" [attr.aria-label]="I18N.stats.categories_score_profile | translate"></canvas>
                          </div>
                        </div>
                        <details class="mt-2 text-sm">
                          <summary class="min-h-11 cursor-pointer content-center text-[var(--mat-sys-primary)]">{{ I18N.stats.show_chart_data | translate }}</summary>
                          <div class="overflow-x-auto"><table class="w-full min-w-max border-collapse text-left [&_th]:whitespace-nowrap [&_th]:px-2 [&_th]:py-1 [&_td]:px-2 [&_td]:py-1 [&_td]:text-right [&_td]:tabular-nums">
                            <caption class="sr-only">{{ I18N.stats.categories_score_profile | translate }}</caption>
                            <thead><tr>
                              <th scope="col">{{ I18N.stats.categories.tab | translate }}</th>
                              @for (def of selectedProfileDefs(); track def.key) {
                                <th scope="col" class="text-right">{{ def.labelKey | translate }}</th>
                              }
                            </tr></thead>
                            <tbody>@for (cat of categoryProfileRows(); track cat.category) {
                              <tr>
                                <th scope="row">{{ cat.label }}</th>
                                @for (def of selectedProfileDefs(); track def.key) {
                                  <td>{{ cat[def.field] | statsNumber:i18n.locale():1 }}</td>
                                }
                              </tr>
                            }</tbody>
                          </table></div>
                        </details>
                      }
                    </mat-card-content>
                  </mat-card>
                }

                <mat-card class="lg:col-span-2 2xl:col-span-1">
                  <mat-card-header class="!flex !items-center !justify-between">
                    <h2 mat-card-title>{{ I18N.stats.score_histogram | translate }}</h2>
                    <button mat-icon-button class="shrink-0" [disabled]="scoreBins().length === 0"
                      [matTooltip]="I18N.stats.export_csv | translate"
                      [attr.aria-label]="I18N.stats.export_csv | translate" (click)="exportScoreBinsCsv()">
                      <mat-icon>download</mat-icon>
                    </button>
                  </mat-card-header>
                  <mat-card-content class="!pt-4">
                    @if (scoreLoading()) {
                      <div class="flex justify-center py-4"><mat-spinner diameter="32" [attr.aria-label]="I18N.ui.labels.loading | translate" /></div>
                    } @else if (scoreFailed()) {
                      <ng-container *ngTemplateOutlet="sectionError; context: { $implicit: 'score' }" />
                    } @else if (scoreBins().length === 0) {
                      <p class="text-sm text-[var(--mat-sys-on-surface-variant)]">{{ I18N.stats.no_data | translate }}</p>
                    } @else {
                      <div [style.height.px]="scoreBins() | chartHeight">
                        <canvas #scoreCanvas role="img" [attr.aria-label]="I18N.stats.score_histogram | translate"></canvas>
                      </div>
                      <table class="sr-only">
                        <caption>{{ I18N.stats.score_histogram | translate }}</caption>
                        <thead><tr><th scope="col">{{ I18N.stats.axes.score | translate }}</th><th scope="col">{{ I18N.stats.axes.photos | translate }}</th></tr></thead>
                        <tbody>
                          @for (bin of scoreChartBins(); track bin.range) {
                            <tr><th scope="row">{{ bin.displayRange }}</th><td>{{ bin.count | statsNumber:i18n.locale() }}</td></tr>
                          }
                        </tbody>
                      </table>
                    }
                  </mat-card-content>
                </mat-card>
              </div>

              <!-- Row 3: Gear table -->
              @if (categoryScoreProfile().length > 0) {
                <mat-card>
                  <mat-card-header class="!flex !items-center !justify-between">
                    <h2 mat-card-title>{{ I18N.stats.categories_gear_profile | translate }}</h2>
                    <div class="flex items-center shrink-0">
                      <button mat-icon-button [disabled]="categoryStats().length === 0"
                        [matTooltip]="I18N.stats.export_csv | translate"
                        [attr.aria-label]="I18N.stats.export_csv | translate" (click)="exportCategoriesCsv()">
                        <mat-icon>download</mat-icon>
                      </button>
                      <button mat-icon-button (click)="showGearProfileHelp.set(!showGearProfileHelp())"
                        [matTooltip]="I18N.stats.gear_profile_help.tooltip | translate" [attr.aria-label]="I18N.stats.gear_profile_help.tooltip | translate">
                        <mat-icon>help_outline</mat-icon>
                      </button>
                    </div>
                  </mat-card-header>
                  @if (showGearProfileHelp()) {
                    <div class="mx-4 mb-2 text-sm text-[var(--mat-sys-on-surface-variant)]">
                      {{ I18N.stats.gear_profile_help.description | translate }}
                    </div>
                  }
                  <mat-card-content class="!pt-4 overflow-x-auto">
                    <table class="w-full text-sm">
                      <thead>
                        <tr class="text-[var(--mat-sys-on-surface-variant)] text-left border-b border-[var(--mat-sys-outline-variant)]">
                          <th class="pb-2 pr-4">{{ I18N.stats.categories.tab | translate }}</th>
                          <th class="pb-2 pr-4">{{ I18N.stats.cameras | translate }}</th>
                          <th class="pb-2 pr-4">{{ I18N.stats.lenses | translate }}</th>
                          <th class="pb-2 pr-4">ISO</th>
                          <th class="pb-2 pr-4">f/</th>
                          <th class="pb-2">mm</th>
                        </tr>
                      </thead>
                      <tbody>
                        @for (cat of categoryScoreProfile(); track cat.category) {
                          <tr class="border-b border-[var(--mat-sys-outline-variant)] hover:bg-[var(--mat-sys-surface-container)]">
                            <td class="py-1.5 pr-4 font-medium" [matTooltip]="('category_names.' + cat.category) | translate">{{ ('category_names.' + cat.category) | translate }}</td>
                            <td class="py-1.5 pr-4 text-[var(--mat-sys-on-surface-variant)] truncate max-w-40" [matTooltip]="cat.top_camera || '—'">{{ cat.top_camera || '—' }}</td>
                            <td class="py-1.5 pr-4 text-[var(--mat-sys-on-surface-variant)] truncate max-w-40" [matTooltip]="cat.top_lens || '—'">{{ cat.top_lens || '—' }}</td>
                            <td class="py-1.5 pr-4 text-[var(--mat-sys-on-surface-variant)]" [matTooltip]="cat.avg_iso > 0 ? (cat.avg_iso | statsNumber:i18n.locale()) : '—'">{{ cat.avg_iso > 0 ? (cat.avg_iso | statsNumber:i18n.locale()) : '—' }}</td>
                            <td class="py-1.5 pr-4 text-[var(--mat-sys-on-surface-variant)]" [matTooltip]="cat.avg_f_stop > 0 ? (cat.avg_f_stop | statsNumber:i18n.locale():1) : '—'">{{ cat.avg_f_stop > 0 ? (cat.avg_f_stop | statsNumber:i18n.locale():1) : '—' }}</td>
                            <td class="py-1.5 text-[var(--mat-sys-on-surface-variant)]" [matTooltip]="cat.avg_focal_length > 0 ? (cat.avg_focal_length | statsNumber:i18n.locale()) : '—'">{{ cat.avg_focal_length > 0 ? (cat.avg_focal_length | statsNumber:i18n.locale()) : '—' }}</td>
                          </tr>
                        }
                      </tbody>
                    </table>
                  </mat-card-content>
                </mat-card>
              }
            </div>
          </mat-tab>

          <!-- Timeline tab -->
          <mat-tab>
            <ng-template mat-tab-label>
              <app-tab-label icon="timeline" [label]="I18N.stats.timeline | translate" />
            </ng-template>
            <app-stats-timeline-tab />
          </mat-tab>

          <!-- Correlations tab -->
          <mat-tab>
            <ng-template mat-tab-label>
              <app-tab-label icon="insights" [label]="I18N.stats.tabs.correlations | translate" />
            </ng-template>
            <app-stats-correlations-tab [active]="selectedTab() === correlationsTab" />
          </mat-tab>
        </mat-tab-group>
      }
  `,
})
export class StatsComponent {
  protected readonly I18N = i18nKeys();
  protected readonly compactTabs = COMPACT_PAGE_TABS;
  private api = inject(ApiService);
  private readonly auth = inject(AuthService);
  private readonly authScope = statsAuthScope(this.auth);
  private readonly document = inject(DOCUMENT);
  private readonly injector = inject(Injector);
  protected readonly i18n = inject(I18nService);
  private destroyRef = inject(DestroyRef);
  private route = inject(ActivatedRoute);
  private router = inject(Router);
  readonly statsFilters = inject(StatsFiltersService);
  readonly store = inject(GalleryStore);
  protected readonly unknownCategory = computed(() => {
    const category = this.statsFilters.filterCategory();
    return category && !this.store.types().some(t => t.id === category) ? category : null;
  });
  protected readonly unknownCategoryLabel = computed(() => {
    const category = this.unknownCategory();
    return category ? this.translateCategory(category) : '';
  });
  protected readonly filterSummary = computed(() => {
    const category = this.statsFilters.filterCategory();
    const displayDate = (date: string) => {
      const parts = /^(\d{4})-(\d{2})-(\d{2})$/.exec(date);
      return parts ? `${parts[3]}/${parts[2]}/${parts[1]}` : date;
    };
    const from = this.statsFilters.dateFrom();
    const to = this.statsFilters.dateTo();
    return [category ? this.translateCategory(category) : '', from ? displayDate(from) : '', to ? displayDate(to) : ''].filter(Boolean).join(' · ');
  });
  readonly themeService = inject(ThemeService);
  private readonly pageHelp = inject(PageHelpService);
  private readonly headerSlot = inject(HeaderSlotService);
  private readonly toolbarTpl = viewChild<TemplateRef<unknown>>('statsToolbar');
  private charts = new Map<string, Chart>();
  private chartRefs = new Map<string, ElementRef<HTMLCanvasElement>>();

  // Canvas refs
  protected readonly scoreCanvas = viewChild<ElementRef<HTMLCanvasElement>>('scoreCanvas');
  protected readonly categoryScoreProfileCanvas = viewChild<ElementRef<HTMLCanvasElement>>('categoryScoreProfileCanvas');
  protected readonly categoryMetricCanvas = viewChild<ElementRef<HTMLCanvasElement>>('categoryMetricCanvas');

  protected readonly selectedTab = signal(0);
  /** Index of the Correlations tab, the last one: it queries only while shown. */
  protected readonly correlationsTab = 3;

  // Filter controls (shared with app header via StatsFiltersService)
  protected get dateFrom() { return this.statsFilters.dateFrom; }
  protected get dateTo() { return this.statsFilters.dateTo; }
  protected get filterCategory() { return this.statsFilters.filterCategory; }

  protected onStatsCategoryChange(cat: string): void {
    this.statsFilters.filterCategory.set(cat);
  }

  protected readonly loading = signal(true);
  protected readonly loadFailed = signal(false);
  protected readonly retrying = signal(false);

  protected readonly cameras = signal<GearItem[]>([]);
  protected readonly lenses = signal<GearItem[]>([]);
  protected readonly combos = signal<GearItem[]>([]);
  protected readonly gearLoading = signal(false);
  // A failed section read degrades that section only; `loadFailed` is reserved for the overview.
  protected readonly gearFailed = signal(false);
  protected readonly categoriesFailed = signal(false);
  protected readonly scoreFailed = signal(false);

  protected readonly categoryStats = signal<CategoryStat[]>([]);
  protected readonly categoriesLoading = signal(false);
  protected readonly showGearProfileHelp = signal(false);

  categoryScoreProfile = computed(() => [...this.categoryStats()].filter(c => c.avg_score > 0).sort((a, b) => b.avg_score - a.avg_score));

  protected readonly categoryMetricOptions = [
    { key: 'avg_f_stop' }, { key: 'avg_focal_length' }, { key: 'avg_iso' },
    { key: 'avg_score' }, { key: 'avg_aesthetic' }, { key: 'avg_sharpness' }, { key: 'avg_contrast' },
  ];
  protected readonly categoryMetric = signal('avg_f_stop');

  /** The score-profile chart's series in chart order; `colorIndex` keeps each series' colour when others are hidden. */
  protected readonly profileSeriesDefs: readonly { key: string; field: ProfileField; labelKey: string; colorIndex: number }[] = [
    { key: 'aggregate', field: 'avg_score', labelKey: I18N.stats.axes.aggregate, colorIndex: 0 },
    { key: 'aesthetic', field: 'avg_aesthetic', labelKey: I18N.stats.axes.aesthetic, colorIndex: 1 },
    { key: 'comp_score', field: 'avg_composition', labelKey: I18N.stats.axes.composition, colorIndex: 2 },
    { key: 'tech_sharpness', field: 'avg_sharpness', labelKey: I18N.stats.axes.sharpness, colorIndex: 3 },
    { key: 'color_score', field: 'avg_color', labelKey: I18N.stats.axes.color, colorIndex: 4 },
    { key: 'exposure_score', field: 'avg_exposure', labelKey: I18N.stats.axes.exposure, colorIndex: 5 },
    { key: 'face_quality', field: 'avg_face_quality', labelKey: I18N.stats.axes.face_quality, colorIndex: 6 },
    { key: 'contrast_score', field: 'avg_contrast', labelKey: I18N.stats.axes.contrast, colorIndex: 7 },
  ];
  /** Series shown on the score-profile chart: all of them at first, never persisted, never empty. */
  protected readonly profileSeries = signal<string[]>(this.profileSeriesDefs.map(def => def.key));
  protected readonly selectedProfileDefs = computed(() => this.profileSeriesDefs.filter(def => this.profileSeries().includes(def.key)));
  protected readonly profileColors = computed(() => chartSeriesColors(this.themeService.darkMode()));
  /** "N scores" once the swatches no longer fit the trigger; null while they do. */
  protected readonly profileSeriesSummary = computed(() => {
    const count = this.selectedProfileDefs().length;
    return count > 3 ? this.i18n.t(I18N.stats.profile_series_count, { count }) : null;
  });

  protected onProfileSeriesChange(keys: string[]): void {
    const next = this.profileSeriesDefs.map(def => def.key).filter(key => keys.includes(key));
    // The last series stays: re-set a copy so the select re-applies its selection to the option the user just cleared.
    this.profileSeries.set(next.length > 0 ? next : [...this.profileSeries()]);
  }
  protected readonly categoryMetricDigits = computed(() =>
    this.categoryMetric() === 'avg_iso' || this.categoryMetric() === 'avg_focal_length' ? 0 : 1,
  );
  protected readonly categoryMetricData = computed(() => {
    const metric = this.categoryMetric() as keyof CategoryStat;
    return [...this.categoryStats()]
      .filter(c => (c[metric] as number) > 0)
      .sort((a, b) => (b[metric] as number) - (a[metric] as number));
  });
  protected readonly categoryMetricRows = computed(() => {
    const metric = this.categoryMetric() as keyof CategoryStat;
    return this.categoryMetricData().map(cat => ({ category: cat.category, label: this.translateCategory(cat.category), value: cat[metric] as number }));
  });
  protected readonly categoryProfileRows = computed(() => this.categoryScoreProfile().map(cat => ({ ...cat, label: this.translateCategory(cat.category) })));

  protected readonly scoreBins = signal<ScoreBin[]>([]);
  protected readonly scoreDisplayBins = computed(() => {
    const formatter = new Intl.NumberFormat(this.i18n.locale(), { maximumFractionDigits: 1 });
    return this.scoreBins().map(bin => {
      const value = Number(bin.range);
      // The API's bucket is a rounded score, not the lower edge of an interval.
      return { ...bin, displayRange: bin.range.trim() && Number.isFinite(value) ? formatter.format(value) : bin.range };
    });
  });
  /** The API omits empty rounded buckets; keep their positions on the chart. */
  protected readonly scoreChartBins = computed(() => {
    const bins = this.scoreDisplayBins();
    if (!bins.length) return bins;
    const byStep = new Map<number, (typeof bins)[number]>();
    for (const bin of bins) {
      const value = Number(bin.range), step = Math.round(value * 2);
      if (!bin.range.trim() || !Number.isFinite(value) || Math.abs(value * 2 - step) > 1e-8 || byStep.has(step)) return bins;
      byStep.set(step, bin);
    }
    const steps = [...byStep.keys()].sort((a, b) => a - b);
    const first = steps[0] >= 0 && steps[steps.length - 1] <= 20 ? 0 : steps[0];
    const last = steps[0] >= 0 && steps[steps.length - 1] <= 20 ? 20 : steps[steps.length - 1];
    // Do not allocate an unbounded array for corrupt or unsupported values.
    if (last - first > 400) return bins;
    const formatter = new Intl.NumberFormat(this.i18n.locale(), { maximumFractionDigits: 1 });
    return Array.from({ length: last - first + 1 }, (_, offset) => {
      const step = first + offset, value = step / 2;
      return byStep.get(step) ?? { range: String(value), min: value, max: value, count: 0, percentage: 0, displayRange: formatter.format(value) };
    });
  });
  protected readonly scoreLoading = signal(false);

  constructor() {
    registerPageContext('stats', () => ({
      tab: this.selectedTab(),
      category: this.statsFilters.filterCategory(),
      date_from: this.statsFilters.dateFrom(),
      date_to: this.statsFilters.dateTo(),
    }));
    this.pageHelp.setDescription(I18N.stats.help);

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
       
      const qp: any = { category: cat || null, date_from: from || null, date_to: to || null };
      this.router.navigate([], { queryParams: qp, queryParamsHandling: 'merge', replaceUrl: true });
    });

    // Reload when filter signals change
    effect(() => {
      this.statsFilters.filterCategory();
      this.statsFilters.dateFrom();
      this.statsFilters.dateTo();
      // Reload when the identity or token changes, not on every status refresh.
      this.authScope();
      const authenticated = this.auth.isAuthenticated();
      untracked(() => {
        if (authenticated) void this.loadAll();
        else this.clearStats();
      });
    });

    effect(() => {
      const t = this.toolbarTpl();
      if (t) this.headerSlot.set(t);
    });

    // Destroy Chart.js instances and clear shared state on component teardown
    this.destroyRef.onDestroy(() => {
      this.charts.forEach(chart => chart.destroy());
      this.charts.clear();
      this.statsFilters.overview.set(null);
      this.pageHelp.setDescription(null);
      const t = this.toolbarTpl();
      if (t) this.headerSlot.clear(t);
    });

    // Chart effects — canvas refs must be tracked so charts render on tab switch
    effect(() => {
      const bins = this.scoreChartBins();
      const accent = chartSeriesColor(this.themeService.accentColor(), this.themeService.darkMode());
      this.buildVerticalBar('score', this.scoreCanvas(), bins.map(b => b.displayRange), bins.map(b => b.count), accent);
    });
    effect(() => {
      const cats = this.categoryScoreProfile();
      const colors = this.profileColors();
      const labels = cats.map(c => this.translateCategory(c.category));
      this.buildGroupedHorizontalBar('categoryScoreProfile', this.categoryScoreProfileCanvas(), labels,
        this.selectedProfileDefs().map(def => ({ label: this.i18n.t(def.labelKey), data: cats.map(c => c[def.field]), color: colors[def.colorIndex] })));
    });
    effect(() => {
      const cats = this.categoryMetricData();
      const metric = this.categoryMetric() as keyof CategoryStat;
      const color = chartSeriesColor(this.themeService.complementaryColor(), this.themeService.darkMode());
      this.buildHorizontalBar('categoryMetric', this.categoryMetricCanvas(),
        cats.map(c => this.translateCategory(c.category)), cats.map(c => c[metric] as number), color);
    });
  }

  private get filterParams(): Record<string, string> {
    const params: Record<string, string> = {};
    if (this.dateFrom()) params['date_from'] = this.dateFrom();
    if (this.dateTo()) params['date_to'] = this.dateTo();
    if (this.filterCategory()) params['category'] = this.filterCategory();
    return params;
  }

  private readonly loadSeq: Record<string, number> = {};
  private nextLoadSeq(key: string): number { return (this.loadSeq[key] = (this.loadSeq[key] ?? 0) + 1); }
  private captureLoad(key: string): () => boolean {
    const seq = this.nextLoadSeq(key);
    const owner = this.auth.identity();
    const token = this.auth.token;
    return () => !this.destroyRef.destroyed && this.auth.isAuthenticated()
      && this.auth.identity() === owner && this.auth.token === token && this.loadSeq[key] === seq;
  }

  private clearStats(): void {
    for (const key of ['overview', 'gear', 'categories', 'scoreDistribution']) this.nextLoadSeq(key);
    this.statsFilters.overview.set(null);
    this.cameras.set([]); this.lenses.set([]); this.combos.set([]);
    this.categoryStats.set([]); this.scoreBins.set([]);
    this.loading.set(false); this.gearLoading.set(false); this.categoriesLoading.set(false); this.scoreLoading.set(false);
    this.gearFailed.set(false); this.categoriesFailed.set(false); this.scoreFailed.set(false);
    this.loadFailed.set(false);
    this.retrying.set(false);
  }

  private localErrors(): HttpContext {
    return new HttpContext().set(HANDLE_SERVER_ERROR_LOCALLY, true);
  }

  protected retryLoad(): void {
    if (!this.retrying()) void this.loadAll(true);
  }

  protected retrySection(section: 'gear' | 'categories' | 'score'): void {
    if (section === 'gear') void this.loadGear();
    else if (section === 'categories') void this.loadCategories();
    else void this.loadScoreDistribution();
  }

  async loadAll(retry = false): Promise<void> {
    const retryButton = retry ? this.document.querySelector<HTMLButtonElement>('[data-stats-retry]') : null;
    this.clearStats();
    if (!this.auth.isAuthenticated() || this.destroyRef.destroyed) return;
    const current = this.captureLoad('overview');
    this.retrying.set(retry);
    // Invalidate outstanding chart reads as soon as filters change, not after
    // the new overview has returned. An older response must not reappear.
    this.loading.set(true);
    let overviewLoaded = false;
    try {
      const overview = await firstValueFrom(this.api.get<StatsOverviewData>('/stats/overview', this.filterParams, this.localErrors()));
      if (current()) { this.statsFilters.overview.set(overview); overviewLoaded = true; }
    } catch { if (current()) this.loadFailed.set(true); }
    finally { if (current()) this.loading.set(false); }

    if (!current()) return;
    if (overviewLoaded) {
      await Promise.all([this.loadGear(), this.loadCategories(), this.loadScoreDistribution()]);
    }
    if (!current()) return;
    const restoreFocus = retry && !this.loadFailed() && this.document.activeElement === retryButton;
    this.retrying.set(false);
    if (restoreFocus) afterNextRender(() => {
      if (current() && (this.document.activeElement === retryButton || this.document.activeElement === this.document.body))
        this.document.getElementById('stats-heading')?.focus();
    }, { injector: this.injector });
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
    const current = this.captureLoad('gear');
    this.gearLoading.set(true);
    this.gearFailed.set(false);
    try {
      const data = await firstValueFrom(this.api.get<GearApiResponse>('/stats/gear', this.filterParams, this.localErrors()));
      if (current()) {
        this.cameras.set((data.cameras ?? []).map(c => this.mapGearItem(c as unknown as Record<string, unknown>)));
        this.lenses.set((data.lenses ?? []).map(l => this.mapGearItem(l as unknown as Record<string, unknown>)));
        this.combos.set((data.combos ?? []).map(c => this.mapGearItem(c as unknown as Record<string, unknown>)));
      }
    } catch { if (current()) this.gearFailed.set(true); }
    finally { if (current()) this.gearLoading.set(false); }
  }

  async loadCategories(): Promise<void> {
    const current = this.captureLoad('categories');
    this.categoriesLoading.set(true);
    this.categoriesFailed.set(false);
    try {
      const data = await firstValueFrom(this.api.get<CategoryStat[]>('/stats/categories', this.filterParams, this.localErrors()));
      if (current()) this.categoryStats.set(data);
    } catch { if (current()) this.categoriesFailed.set(true); }
    finally { if (current()) this.categoriesLoading.set(false); }
  }

  async loadScoreDistribution(): Promise<void> {
    const current = this.captureLoad('scoreDistribution');
    this.scoreLoading.set(true);
    this.scoreFailed.set(false);
    try {
      const data = await firstValueFrom(this.api.get<ScoreBin[]>('/stats/score_distribution', this.filterParams, this.localErrors()));
      if (current()) this.scoreBins.set(data);
    } catch { if (current()) this.scoreFailed.set(true); }
    finally { if (current()) this.scoreLoading.set(false); }
  }

  /** Export the per-category statistics table as CSV. */
  protected exportCategoriesCsv(): void {
    downloadCsv('facet-categories', this.categoryStats());
  }

  /** Export the score-distribution histogram as CSV. */
  protected exportScoreBinsCsv(): void {
    downloadCsv('facet-score-distribution', this.scoreBins());
  }

  private translateCategory(name: string): string {
    const key = name === 'top_picks' ? 'photo_types.top_picks' : `category_names.${name}`;
    const translated = this.i18n.t(key);
    return translated === key ? name : translated;
  }

  private updateChartTheme(chart: Chart): void {
    const { text, grid } = chartTheme();
    for (const scale of Object.values(chart.options.scales ?? {})) {
      if (!scale) continue;
      if (scale.ticks) scale.ticks.color = text;
      if (scale.grid && scale.grid.display !== false) scale.grid.color = grid;
    }
    const labels = chart.options.plugins?.legend?.labels;
    if (labels) labels.color = text;
  }

  private buildHorizontalBar(id: string, ref: ElementRef<HTMLCanvasElement> | undefined, labels: string[], data: number[], color: string): void {
    if (!ref || data.length === 0) { this.destroyChart(id); return; }
    // Skip rebuild if same canvas ref and chart already exists — just update data
    const existing = this.charts.get(id);
    if (existing && this.chartRefs.get(id) === ref) {
      existing.data.labels = labels;
      existing.data.datasets[0].data = data;
      existing.data.datasets[0].backgroundColor = color + 'cc';
      existing.data.datasets[0].borderColor = color;
      this.updateChartTheme(existing);
      existing.update('none');
      return;
    }
    this.destroyChart(id);
    this.chartRefs.set(id, ref);
    const ctx = ref.nativeElement.getContext('2d');
    if (!ctx) return;
    const { text, grid } = chartTheme();
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
          tooltip: { callbacks: { label: (ctx) => (ctx.parsed.x ?? 0).toLocaleString(this.i18n.locale()) } },
        },
        scales: {
          x: { grid: { color: grid }, ticks: { color: text } },
          y: { grid: { display: false }, ticks: { color: text, font: { size: 11 } } },
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
    if (!ref || labels.length === 0) { this.destroyChart(id); return; }
    const existing = this.charts.get(id);
    if (existing && this.chartRefs.get(id) === ref && existing.data.datasets.length === datasets.length) {
      existing.data.labels = labels;
      datasets.forEach((d, i) => {
        if (existing.data.datasets[i]) {
          existing.data.datasets[i].label = d.label;
          existing.data.datasets[i].data = d.data;
          (existing.data.datasets[i] as any).backgroundColor = d.color + 'bb';
          (existing.data.datasets[i] as any).borderColor = d.color;
        }
      });
      this.updateChartTheme(existing);
      existing.update('none');
      return;
    }
    this.destroyChart(id);
    this.chartRefs.set(id, ref);
    const ctx = ref.nativeElement.getContext('2d');
    if (!ctx) return;
    const { text, grid } = chartTheme();
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
          // Passive colour key for the multi-select: series are chosen there, so a legend click does nothing.
          legend: { display: true, position: 'top', onClick: () => undefined, labels: { color: text, boxWidth: 12 } },
          tooltip: { callbacks: { label: (ctx) => `${ctx.dataset.label}: ${(ctx.parsed.x ?? 0).toFixed(2)}` } },
        },
        scales: {
          x: { grid: { color: grid }, ticks: { color: text }, min: 0, max: 10 },
          y: { grid: { display: false }, ticks: { color: text, font: { size: 11 } } },
        },
      },
    }));
  }

  private buildVerticalBar(id: string, ref: ElementRef<HTMLCanvasElement> | undefined, labels: string[], data: number[], color: string): void {
    if (!ref || data.length === 0) { this.destroyChart(id); return; }
    const formatter = new Intl.NumberFormat(this.i18n.locale());
    const existing = this.charts.get(id);
    if (existing && this.chartRefs.get(id) === ref) {
      existing.data.labels = labels;
      existing.data.datasets[0].data = data;
      existing.data.datasets[0].backgroundColor = color + 'cc';
      existing.data.datasets[0].borderColor = color;
      this.updateChartTheme(existing);
      const ticks = existing.options.scales?.['y']?.ticks;
      if (ticks) ticks.callback = value => formatter.format(Number(value));
      existing.update('none');
      return;
    }
    this.destroyChart(id);
    this.chartRefs.set(id, ref);
    const ctx = ref.nativeElement.getContext('2d');
    if (!ctx) return;
    const { text, grid } = chartTheme();
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
          tooltip: { callbacks: { label: (ctx) => new Intl.NumberFormat(this.i18n.locale()).format(ctx.parsed.y ?? 0) } },
        },
        scales: {
          x: { grid: { display: false }, ticks: { color: text, maxRotation: 45 } },
          y: { grid: { color: grid }, ticks: { color: text, callback: value => formatter.format(Number(value)) } },
        },
      },
    }));
  }

  private destroyChart(id: string): void {
    const existing = this.charts.get(id);
    if (existing) {
      existing.destroy();
      this.charts.delete(id);
      this.chartRefs.delete(id);
    }
  }
}
