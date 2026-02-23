import { Component, inject, signal, computed, viewChild, ElementRef, effect, DestroyRef } from '@angular/core';
import { toObservable, takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { FormsModule } from '@angular/forms';
import { MatCardModule } from '@angular/material/card';
import { MatSliderModule } from '@angular/material/slider';
import { MatButtonModule } from '@angular/material/button';
import { MatIconModule } from '@angular/material/icon';
import { MatFormFieldModule } from '@angular/material/form-field';
import { MatInputModule } from '@angular/material/input';
import { MatSelectModule } from '@angular/material/select';
import { MatCheckboxModule } from '@angular/material/checkbox';
import { MatDividerModule } from '@angular/material/divider';
import { MatProgressSpinnerModule } from '@angular/material/progress-spinner';
import { MatTooltipModule } from '@angular/material/tooltip';
import { MatSnackBar } from '@angular/material/snack-bar';
import { firstValueFrom, debounceTime, skip, filter } from 'rxjs';
import { Chart } from 'chart.js';
import { ApiService } from '../../core/services/api.service';
import { I18nService } from '../../core/services/i18n.service';
import { ThemeService } from '../../core/services/theme.service';
import { TranslatePipe } from '../../shared/pipes/translate.pipe';
import { FixedPipe } from '../../shared/pipes/fixed.pipe';
import { ThumbnailUrlPipe } from '../../shared/pipes/thumbnail-url.pipe';
import { CompareFiltersService } from './compare-filters.service';
import { WeightIconPipe, WeightLabelKeyPipe } from './comparison.pipes';

interface CategoryWeights {
  weights: Record<string, number>;
  modifiers: Record<string, number | boolean | string>;
  filters: Record<string, unknown>;
}

interface PreviewPhoto {
  path: string;
  filename: string;
  aggregate: number;
  aesthetic: number;
  comp_score: number;
  face_quality: number;
  new_score?: number;
}

interface WeightImpactResponse {
  correlations: Record<string, Record<string, number>>;
  configured_weights: Record<string, Record<string, number>>;
  dimensions: string[];
}

const BOOLEAN_FILTER_KEYS = ['has_face', 'is_monochrome', 'is_silhouette', 'is_group_portrait'] as const;

const NUMERIC_FILTER_RANGES: [string, string, string][] = [
  ['face_ratio_min', 'face_ratio_max', 'comparison.filter.face_ratio'],
  ['face_count_min', 'face_count_max', 'comparison.filter.face_count'],
  ['iso_min', 'iso_max', 'comparison.filter.iso'],
  ['shutter_speed_min', 'shutter_speed_max', 'comparison.filter.shutter_speed'],
  ['focal_length_min', 'focal_length_max', 'comparison.filter.focal_length'],
  ['f_stop_min', 'f_stop_max', 'comparison.filter.f_stop'],
  ['luminance_min', 'luminance_max', 'comparison.filter.luminance'],
];

class SignalErrorMatcher {
  constructor(private readonly check: () => boolean) {}
  isErrorState(_ctrl: unknown, _form: unknown): boolean { return this.check(); }
}

@Component({
  selector: 'app-comparison-weights-tab',
  standalone: true,
  imports: [
    FormsModule,
    MatCardModule,
    MatSliderModule,
    MatButtonModule,
    MatIconModule,
    MatFormFieldModule,
    MatInputModule,
    MatSelectModule,
    MatCheckboxModule,
    MatDividerModule,
    MatProgressSpinnerModule,
    MatTooltipModule,
    TranslatePipe,
    FixedPipe,
    ThumbnailUrlPipe,
    WeightIconPipe,
    WeightLabelKeyPipe,
  ],
  template: `
    <div class="grid grid-cols-1 lg:grid-cols-2 gap-6 mt-4">
      <!-- Left: Weight sliders -->
      <mat-card>
        <mat-card-header class="!flex !items-start">
          <div class="flex-1">
            <mat-card-title>{{ 'comparison.weight_sliders' | translate }}</mat-card-title>
            <mat-card-subtitle>
              {{ 'comparison.total' | translate }}: {{ weightTotal() }}%
              @if (weightTotal() !== 100) {
                <span class="text-amber-400">
                  ({{ 'comparison.should_be_100' | translate }})
                </span>
              }
            </mat-card-subtitle>
          </div>
          @if (weightTotal() !== 100) {
            <button mat-icon-button class="!w-8 !h-8 shrink-0" (click)="normalizeWeights()"
              [matTooltip]="'stats.categories.weights.normalize' | translate">
              <mat-icon>balance</mat-icon>
            </button>
          }
        </mat-card-header>
        <mat-card-content class="!pt-4">
          @if (loading()) {
            <div class="flex justify-center py-8">
              <mat-spinner diameter="40" />
            </div>
          } @else {
            <div class="flex flex-col gap-4">
              @for (key of weightKeys(); track key) {
                <div class="flex items-center gap-3">
                  <mat-icon class="text-gray-400 shrink-0">{{ key | weightIcon }}</mat-icon>
                  <span class="w-40 shrink-0 text-sm">
                    {{ key | weightLabelKey | translate }}
                  </span>
                  <mat-slider class="grow" [min]="0" [max]="100" [step]="1" [discrete]="true" [showTickMarks]="false">
                    <input matSliderThumb [value]="weights()[key]" (valueChange)="setWeight(key, $event)" />
                  </mat-slider>
                  <span class="w-12 text-right text-sm font-mono tabular-nums">{{ weights()[key] }}%</span>
                </div>
              }
            </div>
          }
        </mat-card-content>
      </mat-card>

      <!-- Right: Weight Impact chart -->
      <mat-card>
        <mat-card-header>
          <mat-card-title>{{ 'stats.weight_impact.title' | translate }}</mat-card-title>
          <mat-card-subtitle>{{ 'stats.weight_impact.description' | translate }}</mat-card-subtitle>
        </mat-card-header>
        <mat-card-content class="!pt-4">
          @if (weightImpactLoading()) {
            <div class="flex justify-center py-8"><mat-spinner diameter="32" /></div>
          } @else if (weightImpactData()) {
            <div class="h-80">
              <canvas #weightImpactCanvas></canvas>
            </div>
          } @else {
            <p class="text-sm text-gray-400">{{ 'stats.weight_impact.empty' | translate }}</p>
          }
        </mat-card-content>
      </mat-card>
    </div>

    <!-- Thumbnail preview (full width below the grid) -->
    <mat-card class="mt-6">
      <mat-card-header>
        <mat-card-title class="flex items-center gap-2">
          {{ 'comparison.preview' | translate }}
          @if (previewLoading()) {
            <mat-spinner diameter="18" />
          }
        </mat-card-title>
        <mat-card-subtitle>{{ 'comparison.top_n_photos' | translate:{ count: previewCount } }}</mat-card-subtitle>
      </mat-card-header>
      <mat-card-content class="!pt-4">
        @if (previewPhotos().length > 0) {
          <div class="grid grid-cols-3 md:grid-cols-6 gap-3">
            @for (photo of previewPhotos(); track photo.path; let i = $index) {
              <div class="relative rounded-lg overflow-hidden bg-neutral-900">
                <img [src]="photo.path | thumbnailUrl:320" [alt]="photo.filename" class="w-full object-contain bg-neutral-900" />
                <div class="absolute bottom-0 inset-x-0 bg-gradient-to-t from-black/80 to-transparent px-2 py-1.5">
                  <span class="text-xs font-mono text-white">#{{ i + 1 }}</span>
                  <span class="text-xs font-mono text-gray-300 ml-2">{{ (photo.new_score ?? photo.aggregate) | fixed:1 }}</span>
                </div>
              </div>
            }
          </div>
        } @else if (!previewLoading()) {
          <p class="text-gray-500 text-sm">{{ 'comparison.no_preview' | translate }}</p>
        }
      </mat-card-content>
    </mat-card>

    <!-- Modifiers & Filters -->
    <div class="grid grid-cols-1 lg:grid-cols-2 gap-6 mt-6">
      <!-- Modifiers -->
      <mat-card>
        <mat-card-header>
          <mat-card-title>{{ 'comparison.modifiers' | translate }}</mat-card-title>
          <mat-card-subtitle>{{ 'comparison.modifiers_description' | translate }}</mat-card-subtitle>
        </mat-card-header>
        <mat-card-content class="!pt-4">
          <div class="flex flex-col gap-4">
            <mat-form-field>
              <mat-label>{{ 'comparison.modifier.bonus' | translate }}</mat-label>
              <input matInput type="number" step="0.1" min="-5" max="5"
                [errorStateMatcher]="modifierMatchers['bonus']"
                [ngModel]="getModifierNum('bonus')"
                (ngModelChange)="setModifierNum('bonus', $event)" />
              <mat-hint>{{ 'comparison.modifier.bonus_hint' | translate }}</mat-hint>
              @if (modifierErrors()['bonus']) {
                <mat-error>{{ modifierErrors()['bonus'] | translate }}</mat-error>
              }
            </mat-form-field>
            <mat-form-field>
              <mat-label>{{ 'comparison.modifier.noise_tolerance' | translate }}</mat-label>
              <input matInput type="number" step="0.1" min="0" max="2"
                [errorStateMatcher]="modifierMatchers['noise_tolerance_multiplier']"
                [ngModel]="getModifierNum('noise_tolerance_multiplier')"
                (ngModelChange)="setModifierNum('noise_tolerance_multiplier', $event)" />
              <mat-hint>{{ 'comparison.modifier.noise_tolerance_hint' | translate }}</mat-hint>
              @if (modifierErrors()['noise_tolerance_multiplier']) {
                <mat-error>{{ modifierErrors()['noise_tolerance_multiplier'] | translate }}</mat-error>
              }
            </mat-form-field>
            <mat-form-field>
              <mat-label>{{ 'comparison.modifier.clipping_multiplier' | translate }}</mat-label>
              <input matInput type="number" step="0.1" min="0" max="5"
                [errorStateMatcher]="modifierMatchers['_clipping_multiplier']"
                [ngModel]="getModifierNum('_clipping_multiplier')"
                (ngModelChange)="setModifierNum('_clipping_multiplier', $event)" />
              <mat-hint>{{ 'comparison.modifier.clipping_multiplier_hint' | translate }}</mat-hint>
              @if (modifierErrors()['_clipping_multiplier']) {
                <mat-error>{{ modifierErrors()['_clipping_multiplier'] | translate }}</mat-error>
              }
            </mat-form-field>
            <mat-divider />
            <div class="flex flex-col gap-0.5">
              <mat-checkbox [checked]="!!modifiers()['_skip_clipping_penalty']" (change)="setModifierBool('_skip_clipping_penalty', $event.checked)">
                {{ 'comparison.modifier.skip_clipping_penalty' | translate }}
              </mat-checkbox>
              <p class="text-xs text-gray-500 ml-8">{{ 'comparison.modifier.skip_clipping_penalty_hint' | translate }}</p>
            </div>
            <div class="flex flex-col gap-0.5">
              <mat-checkbox [checked]="!!modifiers()['_skip_oversaturation_penalty']" (change)="setModifierBool('_skip_oversaturation_penalty', $event.checked)">
                {{ 'comparison.modifier.skip_oversaturation_penalty' | translate }}
              </mat-checkbox>
              <p class="text-xs text-gray-500 ml-8">{{ 'comparison.modifier.skip_oversaturation_penalty_hint' | translate }}</p>
            </div>
            <div class="flex flex-col gap-0.5">
              <mat-checkbox [checked]="!!modifiers()['_apply_blink_penalty']" (change)="setModifierBool('_apply_blink_penalty', $event.checked)">
                {{ 'comparison.modifier.apply_blink_penalty' | translate }}
              </mat-checkbox>
              <p class="text-xs text-gray-500 ml-8">{{ 'comparison.modifier.apply_blink_penalty_hint' | translate }}</p>
            </div>
          </div>
        </mat-card-content>
      </mat-card>

      <!-- Filters -->
      <mat-card>
        <mat-card-header>
          <mat-card-title>{{ 'comparison.filters' | translate }}</mat-card-title>
          <mat-card-subtitle>{{ 'comparison.filters_description' | translate }}</mat-card-subtitle>
        </mat-card-header>
        <mat-card-content class="!pt-4">
          <div class="flex flex-col gap-4">
            <mat-form-field>
              <mat-label>{{ 'comparison.filter.required_tags' | translate }}</mat-label>
              <input matInput type="text" [placeholder]="'comparison.filter.tags_placeholder' | translate"
                [ngModel]="getFilterTags('required_tags')" (ngModelChange)="setFilterTags('required_tags', $event)" />
              <mat-hint>{{ 'comparison.filter.required_tags_hint' | translate }}</mat-hint>
            </mat-form-field>
            <mat-form-field>
              <mat-label>{{ 'comparison.filter.excluded_tags' | translate }}</mat-label>
              <input matInput type="text" [placeholder]="'comparison.filter.tags_placeholder' | translate"
                [ngModel]="getFilterTags('excluded_tags')" (ngModelChange)="setFilterTags('excluded_tags', $event)" />
              <mat-hint>{{ 'comparison.filter.excluded_tags_hint' | translate }}</mat-hint>
            </mat-form-field>
            <mat-form-field>
              <mat-label>{{ 'comparison.filter.tag_match_mode' | translate }}</mat-label>
              <mat-select [value]="filters()['tag_match_mode'] ?? 'any'" (selectionChange)="setFilter('tag_match_mode', $event.value)">
                <mat-option value="any">{{ 'comparison.filter.tag_match_any' | translate }}</mat-option>
                <mat-option value="all">{{ 'comparison.filter.tag_match_all' | translate }}</mat-option>
              </mat-select>
              <mat-hint>{{ 'comparison.filter.tag_match_mode_hint' | translate }}</mat-hint>
            </mat-form-field>
            <mat-divider />
            @for (boolKey of booleanFilterKeys; track boolKey) {
              <mat-form-field>
                <mat-label>{{ ('comparison.filter.' + boolKey) | translate }}</mat-label>
                <mat-select [value]="getFilterBoolValue(boolKey)" (selectionChange)="setFilterBool(boolKey, $event.value)">
                  <mat-option value="">{{ 'comparison.filter.any' | translate }}</mat-option>
                  <mat-option value="true">{{ 'comparison.filter.boolean_true' | translate }}</mat-option>
                  <mat-option value="false">{{ 'comparison.filter.boolean_false' | translate }}</mat-option>
                </mat-select>
                <mat-hint>{{ ('comparison.filter.' + boolKey + '_hint') | translate }}</mat-hint>
              </mat-form-field>
            }
            <mat-divider />
            @for (range of numericFilterRanges; track range[0]) {
              <div>
                <div class="text-sm text-gray-400 mb-1">{{ range[2] | translate }}</div>
                <div class="flex gap-2">
                  <mat-form-field class="flex-1" subscriptSizing="dynamic">
                    <mat-label>{{ 'comparison.filter.min' | translate }}</mat-label>
                    <input matInput type="number" [errorStateMatcher]="filterMatchers[range[0]]"
                      [ngModel]="getFilterNum(range[0])" (ngModelChange)="setFilterNum(range[0], $event)" />
                    @if (filterErrors()[range[0]]) {
                      <mat-error>{{ filterErrors()[range[0]] | translate }}</mat-error>
                    }
                  </mat-form-field>
                  <mat-form-field class="flex-1" subscriptSizing="dynamic">
                    <mat-label>{{ 'comparison.filter.max' | translate }}</mat-label>
                    <input matInput type="number" [errorStateMatcher]="filterMatchers[range[1]]"
                      [ngModel]="getFilterNum(range[1])" (ngModelChange)="setFilterNum(range[1], $event)" />
                    @if (filterErrors()[range[1]]) {
                      <mat-error>{{ filterErrors()[range[1]] | translate }}</mat-error>
                    }
                  </mat-form-field>
                </div>
                <p class="text-xs text-gray-500 mt-1">{{ (range[2] + '_hint') | translate }}</p>
              </div>
            }
          </div>
        </mat-card-content>
      </mat-card>
    </div>
  `,
})
export class ComparisonWeightsTabComponent {
  private api = inject(ApiService);
  private i18n = inject(I18nService);
  private snackBar = inject(MatSnackBar);
  private destroyRef = inject(DestroyRef);
  private themeService = inject(ThemeService);
  readonly compareFilters = inject(CompareFiltersService);

  readonly previewCount = 6;
  private charts = new Map<string, Chart>();

  readonly booleanFilterKeys = BOOLEAN_FILTER_KEYS;
  readonly numericFilterRanges = NUMERIC_FILTER_RANGES;

  weights = signal<Record<string, number>>({});
  savedWeights = signal<Record<string, number>>({});
  modifiers = signal<Record<string, number | boolean | string>>({});
  savedModifiers = signal<Record<string, number | boolean | string>>({});
  filters = signal<Record<string, unknown>>({});
  savedFilters = signal<Record<string, unknown>>({});
  loading = signal(false);
  saving = signal(false);
  recalculating = signal(false);

  previewPhotos = signal<PreviewPhoto[]>([]);
  previewLoading = signal(false);

  weightImpactData = signal<WeightImpactResponse | null>(null);
  weightImpactLoading = signal(false);
  weightImpactCanvas = viewChild<ElementRef<HTMLCanvasElement>>('weightImpactCanvas');

  weightKeys = computed(() => Object.keys(this.weights()).filter(k => k.endsWith('_percent')));

  weightTotal = computed(() => {
    const w = this.weights();
    return Object.values(w).reduce((sum, v) => sum + (v || 0), 0);
  });

  hasChanges = computed(() => {
    const currentW = this.weights();
    const savedW = this.savedWeights();
    const weightsChanged = Object.keys(currentW).some(k => currentW[k] !== savedW[k]);
    const modifiersChanged = JSON.stringify(this.modifiers()) !== JSON.stringify(this.savedModifiers());
    const filtersChanged = JSON.stringify(this.filters()) !== JSON.stringify(this.savedFilters());
    return weightsChanged || modifiersChanged || filtersChanged;
  });

  modifierErrors = computed<Record<string, string>>(() => {
    const m = this.modifiers();
    const errs: Record<string, string> = {};
    const num = (k: string) => { const v = m[k]; return v !== undefined && v !== null ? +v : undefined; };
    const v1 = num('bonus');
    if (v1 !== undefined && !isNaN(v1) && (v1 < -5 || v1 > 5)) errs['bonus'] = 'comparison.validation.bonus_range';
    const v2 = num('noise_tolerance_multiplier');
    if (v2 !== undefined && !isNaN(v2) && (v2 < 0 || v2 > 2)) errs['noise_tolerance_multiplier'] = 'comparison.validation.noise_tolerance_range';
    const v3 = num('_clipping_multiplier');
    if (v3 !== undefined && !isNaN(v3) && (v3 < 0 || v3 > 5)) errs['_clipping_multiplier'] = 'comparison.validation.clipping_multiplier_range';
    return errs;
  });

  filterErrors = computed<Record<string, string>>(() => {
    const f = this.filters();
    const errs: Record<string, string> = {};
    const num = (k: string) => { const v = f[k]; return v !== undefined && v !== null ? +v : undefined; };
    const inRange = (k: string, lo: number, hi: number, errKey: string) => {
      const v = num(k);
      if (v !== undefined && !isNaN(v) && (v < lo || v > hi)) errs[k] = errKey;
    };
    const nonNeg = (k: string) => {
      const v = num(k);
      if (v !== undefined && !isNaN(v) && v < 0) errs[k] = 'comparison.validation.non_negative';
    };
    const minMax = (kMin: string, kMax: string) => {
      const lo = num(kMin); const hi = num(kMax);
      if (lo !== undefined && hi !== undefined && !isNaN(lo) && !isNaN(hi) && lo > hi) {
        if (!errs[kMin]) errs[kMin] = 'comparison.validation.min_gt_max';
        if (!errs[kMax]) errs[kMax] = 'comparison.validation.min_gt_max';
      }
    };
    inRange('face_ratio_min', 0, 1, 'comparison.validation.ratio_range');
    inRange('face_ratio_max', 0, 1, 'comparison.validation.ratio_range');
    minMax('face_ratio_min', 'face_ratio_max');
    nonNeg('face_count_min'); nonNeg('face_count_max'); minMax('face_count_min', 'face_count_max');
    nonNeg('iso_min'); nonNeg('iso_max'); minMax('iso_min', 'iso_max');
    inRange('shutter_speed_min', 0, 60, 'comparison.validation.shutter_range');
    inRange('shutter_speed_max', 0, 60, 'comparison.validation.shutter_range');
    minMax('shutter_speed_min', 'shutter_speed_max');
    nonNeg('focal_length_min'); nonNeg('focal_length_max'); minMax('focal_length_min', 'focal_length_max');
    nonNeg('f_stop_min'); nonNeg('f_stop_max'); minMax('f_stop_min', 'f_stop_max');
    inRange('luminance_min', 0, 1, 'comparison.validation.ratio_range');
    inRange('luminance_max', 0, 1, 'comparison.validation.ratio_range');
    minMax('luminance_min', 'luminance_max');
    return errs;
  });

  hasValidationErrors = computed(() =>
    Object.keys(this.modifierErrors()).length > 0 || Object.keys(this.filterErrors()).length > 0,
  );

  readonly modifierMatchers: Record<string, SignalErrorMatcher> = {};
  readonly filterMatchers: Record<string, SignalErrorMatcher> = {};

  constructor() {
    // React to category changes
    toObservable(this.compareFilters.selectedCategory).pipe(
      filter(Boolean),
      takeUntilDestroyed(),
    ).subscribe(() => {
      void Promise.all([this.loadWeights(), this.loadWeightImpact()]);
    });

    for (const k of ['bonus', 'noise_tolerance_multiplier', '_clipping_multiplier']) {
      this.modifierMatchers[k] = new SignalErrorMatcher(() => k in this.modifierErrors());
    }
    for (const [minKey, maxKey] of NUMERIC_FILTER_RANGES) {
      this.filterMatchers[minKey] = new SignalErrorMatcher(() => minKey in this.filterErrors());
      this.filterMatchers[maxKey] = new SignalErrorMatcher(() => maxKey in this.filterErrors());
    }

    effect(() => {
      const data = this.weightImpactData();
      const cat = this.compareFilters.selectedCategory();
      if (data && cat) {
        this.buildWeightImpactChart(data, cat);
      }
    });

    toObservable(this.weights).pipe(
      skip(1),
      debounceTime(600),
      takeUntilDestroyed(),
    ).subscribe(() => {
      if (this.compareFilters.selectedCategory()) this.loadPreview();
    });

    this.destroyRef.onDestroy(() => {
      this.charts.forEach(chart => chart.destroy());
      this.charts.clear();
    });
  }

  async loadWeights(): Promise<void> {
    const cat = this.compareFilters.selectedCategory();
    if (!cat) return;
    this.loading.set(true);
    try {
      const data = await firstValueFrom(
        this.api.get<CategoryWeights>('/comparison/category_weights', { category: cat }),
      );
      this.weights.set({ ...data.weights });
      this.savedWeights.set({ ...data.weights });
      this.modifiers.set({ ...(data.modifiers ?? {}) });
      this.savedModifiers.set({ ...(data.modifiers ?? {}) });
      this.filters.set({ ...(data.filters ?? {}) });
      this.savedFilters.set({ ...(data.filters ?? {}) });
    } catch {
      this.snackBar.open(this.i18n.t('comparison.error_loading_weights'), '', { duration: 4000 });
    } finally {
      this.loading.set(false);
    }
  }

  async loadWeightImpact(): Promise<void> {
    this.weightImpactLoading.set(true);
    try {
      const data = await firstValueFrom(this.api.get<WeightImpactResponse>('/stats/categories/correlations'));
      this.weightImpactData.set(data);
    } catch { /* empty */ }
    finally { this.weightImpactLoading.set(false); }
  }

  async loadPreview(): Promise<void> {
    const cat = this.compareFilters.selectedCategory();
    if (!cat) return;
    this.previewLoading.set(true);
    try {
      const data = await firstValueFrom(
        this.api.get<{ photos: PreviewPhoto[] }>('/photos', {
          category: cat, sort: 'aggregate', sort_direction: 'DESC',
          per_page: this.previewCount, page: 1,
          hide_duplicates: true,
        }),
      );
      this.previewPhotos.set(data.photos ?? []);
    } catch {
      this.snackBar.open(this.i18n.t('comparison.error_loading_preview'), '', { duration: 4000 });
    } finally {
      this.previewLoading.set(false);
    }
  }

  setWeight(key: string, value: number): void {
    this.weights.update(w => ({ ...w, [key]: value }));
  }

  normalizeWeights(): void {
    const w = this.weights();
    const total = Object.values(w).reduce((sum, v) => sum + (v || 0), 0);
    if (total === 0) return;
    const factor = 100 / total;
    const normalized: Record<string, number> = {};
    let runningTotal = 0;
    const keys = Object.keys(w);
    for (let i = 0; i < keys.length; i++) {
      if (i === keys.length - 1) {
        normalized[keys[i]] = 100 - runningTotal;
      } else {
        normalized[keys[i]] = Math.round(w[keys[i]] * factor);
        runningTotal += normalized[keys[i]];
      }
    }
    this.weights.set(normalized);
  }

  getModifierNum(key: string): number | null {
    const v = this.modifiers()[key];
    return v !== undefined && v !== null ? (v as number) : null;
  }

  setModifierNum(key: string, value: number | null): void {
    this.modifiers.update(m => {
      const next = { ...m };
      if (value === null || value === undefined || isNaN(value as number)) delete next[key];
      else next[key] = value;
      return next;
    });
  }

  setModifierBool(key: string, value: boolean): void {
    this.modifiers.update(m => {
      const next = { ...m };
      if (!value) delete next[key];
      else next[key] = true;
      return next;
    });
  }

  getFilterTags(key: string): string {
    const v = this.filters()[key];
    if (Array.isArray(v)) return v.join(', ');
    return '';
  }

  setFilterTags(key: string, value: string): void {
    this.filters.update(f => {
      const next = { ...f };
      const tags = value.split(',').map(t => t.trim()).filter(Boolean);
      if (tags.length === 0) delete next[key];
      else next[key] = tags;
      return next;
    });
  }

  getFilterBoolValue(key: string): string {
    const v = this.filters()[key];
    if (v === true) return 'true';
    if (v === false) return 'false';
    return '';
  }

  setFilterBool(key: string, value: string): void {
    this.filters.update(f => {
      const next = { ...f };
      if (value === 'true') next[key] = true;
      else if (value === 'false') next[key] = false;
      else delete next[key];
      return next;
    });
  }

  getFilterNum(key: string): number | null {
    const v = this.filters()[key];
    return v !== undefined && v !== null ? (v as number) : null;
  }

  setFilterNum(key: string, value: number | null): void {
    this.filters.update(f => {
      const next = { ...f };
      if (value === null || value === undefined || isNaN(value as number)) delete next[key];
      else next[key] = value;
      return next;
    });
  }

  setFilter(key: string, value: unknown): void {
    this.filters.update(f => ({ ...f, [key]: value }));
  }

  async saveWeights(): Promise<void> {
    const cat = this.compareFilters.selectedCategory();
    if (!cat) return;
    if (this.weightTotal() !== 100) this.normalizeWeights();
    this.saving.set(true);
    try {
      await firstValueFrom(
        this.api.post('/config/update_weights', {
          category: cat,
          weights: this.weights(),
          modifiers: this.modifiers(),
          filters: this.filters(),
        }),
      );
      this.savedWeights.set({ ...this.weights() });
      this.savedModifiers.set({ ...this.modifiers() });
      this.savedFilters.set({ ...this.filters() });
      this.snackBar.open(this.i18n.t('comparison.weights_saved'), '', { duration: 3000 });
    } catch {
      this.snackBar.open(this.i18n.t('comparison.error_saving_weights'), '', { duration: 4000 });
    } finally {
      this.saving.set(false);
    }
  }

  async recalculateScores(): Promise<void> {
    const cat = this.compareFilters.selectedCategory();
    if (!cat) return;
    this.recalculating.set(true);
    try {
      const result = await firstValueFrom(
        this.api.post<{ success: boolean; message?: string }>('/stats/categories/recompute', { category: cat }),
      );
      this.snackBar.open(result.message ?? this.i18n.t('comparison.recalculated'), '', { duration: 5000 });
      void this.loadPreview();
      void this.loadWeightImpact();
    } catch {
      this.snackBar.open(this.i18n.t('comparison.error_recalculating'), '', { duration: 4000 });
    } finally {
      this.recalculating.set(false);
    }
  }

  private buildWeightImpactChart(data: WeightImpactResponse, category: string): void {
    const ref = this.weightImpactCanvas();
    if (!ref) return;
    const existing = this.charts.get('weightImpact');
    if (existing) { existing.destroy(); this.charts.delete('weightImpact'); }
    const ctx = ref.nativeElement.getContext('2d');
    if (!ctx) return;

    const weights = data.configured_weights?.[category] ?? {};
    const corrs = data.correlations?.[category] ?? {};
    const activeDims = data.dimensions?.length ? data.dimensions : Object.keys(weights);
    if (activeDims.length === 0) return;

    const labels = activeDims.map((d: string) => this.i18n.t('stats.weight_impact.dims.' + d));
    const weightValues = activeDims.map((d: string) => weights[d] ?? 0);
    const corrValues = activeDims.map((d: string) => Math.abs(corrs[d] ?? 0) * 100);

    this.charts.set('weightImpact', new Chart(ctx, {
      type: 'bar',
      data: {
        labels,
        datasets: [
          { label: this.i18n.t('stats.weight_impact.configured'), data: weightValues, backgroundColor: '#3b82f6cc', borderColor: '#3b82f6', borderWidth: 1, borderRadius: 3 },
          { label: this.i18n.t('stats.weight_impact.actual_impact'), data: corrValues, backgroundColor: this.themeService.accentColor() + 'cc', borderColor: this.themeService.accentColor(), borderWidth: 1, borderRadius: 3 },
        ],
      },
      options: {
        indexAxis: 'y',
        responsive: true,
        maintainAspectRatio: false,
        plugins: {
          legend: { display: true, labels: { color: '#d4d4d4', boxWidth: 12 } },
          tooltip: { callbacks: { label: (ctx) => `${ctx.dataset.label}: ${(ctx.parsed.x ?? 0).toFixed(1)}%` } },
        },
        scales: {
          x: { grid: { color: '#262626' }, ticks: { color: '#a3a3a3', callback: (v) => v + '%' }, max: 100 },
          y: { grid: { display: false }, ticks: { color: '#d4d4d4', font: { size: 11 } } },
        },
      },
    }));
  }
}
