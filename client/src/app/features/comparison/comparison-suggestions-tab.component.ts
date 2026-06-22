import { Component, inject, signal, computed, effect, output } from '@angular/core';
import { MatButtonModule } from '@angular/material/button';
import { MatIconModule } from '@angular/material/icon';
import { MatProgressSpinnerModule } from '@angular/material/progress-spinner';
import { MatSnackBar } from '@angular/material/snack-bar';
import { firstValueFrom } from 'rxjs';
import { ApiService } from '../../core/services/api.service';
import { I18nService } from '../../core/services/i18n.service';
import { TranslatePipe } from '../../shared/pipes/translate.pipe';
import { FixedPipe } from '../../shared/pipes/fixed.pipe';
import { ThumbnailUrlPipe } from '../../shared/pipes/thumbnail-url.pipe';
import { CompareFiltersService } from './compare-filters.service';
import { WeightLabelKeyPipe } from './comparison.pipes';

interface LearnedWeightsResponse {
  available: boolean;
  message?: string;
  current_weights?: Record<string, number>;
  suggested_weights?: Record<string, number>;
  accuracy_before?: number;
  accuracy_after?: number;
  suggest_changes?: boolean;
  comparisons_used?: number;
}

interface CategoryWeights {
  weights: Record<string, number>;
  modifiers: Record<string, number | boolean | string>;
  filters: Record<string, unknown>;
}

interface TopPhoto {
  path: string;
  filename: string;
  aggregate: number;
}

@Component({
  selector: 'app-comparison-suggestions-tab',
  imports: [
    MatButtonModule,
    MatIconModule,
    MatProgressSpinnerModule,
    TranslatePipe,
    FixedPipe,
    ThumbnailUrlPipe,
    WeightLabelKeyPipe,
  ],
  template: `
    <div class="pt-2 grid grid-cols-1 lg:grid-cols-3 gap-4 items-start">
      <!-- Column 1: weight suggestions + actions -->
      <div class="rounded-lg bg-[var(--mat-sys-surface-container)] p-4">
        @if (learnedWeights(); as lw) {
          @if (lw.available && lw.suggested_weights) {
            <div class="text-sm space-y-3">
              <div class="text-gray-400">
                {{ 'compare.weights.learned_from' | translate:{ count: lw.comparisons_used ?? 0 } }}
              </div>
              <div class="flex items-center gap-2">
                <span class="text-gray-400">{{ 'compare.weights.prediction_accuracy' | translate }}:</span>
                <span class="font-mono">{{ (lw.accuracy_before ?? 0) | fixed:0 }}%</span>
                <span class="text-gray-500">&rarr;</span>
                <span class="font-mono text-[var(--facet-accent-text)]">{{ (lw.accuracy_after ?? 0) | fixed:0 }}%</span>
              </div>
              <div class="text-xs">
                <div class="flex items-center gap-2 pb-1 mb-1 border-b border-[var(--mat-sys-outline-variant)] text-gray-500 uppercase text-[10px] font-semibold tracking-wide">
                  <span class="flex-1">{{ 'comparison.weight_property' | translate }}</span>
                  <span class="w-12 text-right">{{ 'comparison.weight_current' | translate }}</span>
                  <span class="w-5 shrink-0"></span>
                  <span class="w-12 text-right">{{ 'comparison.weight_suggested' | translate }}</span>
                </div>
                @for (row of weightRows(); track row.key) {
                  <div class="flex items-center gap-2 py-1 border-b border-[var(--mat-sys-outline-variant)]"
                       [class.font-semibold]="row.changed">
                    <span class="flex-1 truncate text-gray-400">{{ row.key | weightLabelKey | translate }}</span>
                    <span class="font-mono w-12 text-right tabular-nums">{{ row.current }}</span>
                    <mat-icon class="!w-5 !h-5 !text-lg !leading-5 text-gray-500 shrink-0">arrow_forward</mat-icon>
                    <span class="font-mono w-12 text-right tabular-nums text-[var(--facet-accent-text)]">{{ row.suggested }}</span>
                  </div>
                }
              </div>
              @if (!lw.suggest_changes) {
                <p class="text-gray-500 text-xs">{{ 'compare.weights.already_good' | translate }}</p>
              }
              @if (needsRecompute()) {
                <p class="text-amber-400 text-xs">{{ 'comparison.recompute_needed' | translate }}</p>
              }
            </div>
          } @else {
            <p class="text-sm text-gray-500">{{ 'comparison.suggestions_insufficient' | translate }}</p>
          }
        }
      </div>

      <!-- Column 2: current top 10 (before) -->
      <div class="rounded-lg bg-[var(--mat-sys-surface-container)] p-4">
        <div class="text-xs font-semibold uppercase opacity-60 mb-3">{{ 'comparison.top_before' | translate }}</div>
        @for (p of topBefore(); track p.path; let i = $index) {
          <div class="relative mb-3">
            <img [src]="p.path | thumbnailUrl:512" class="w-full rounded object-cover" [alt]="p.filename" loading="lazy" />
            <span class="absolute top-1 left-1 px-1.5 py-0.5 rounded bg-black/60 text-white text-xs">{{ i + 1 }}</span>
            <span class="absolute bottom-1 right-1 px-1.5 py-0.5 rounded bg-black/60 text-white text-xs font-mono">{{ p.aggregate | fixed:1 }}</span>
          </div>
        }
      </div>

      <!-- Column 3: top 10 after recompute -->
      <div class="rounded-lg bg-[var(--mat-sys-surface-container)] p-4">
        <div class="text-xs font-semibold uppercase opacity-60 mb-3">{{ 'comparison.top_after' | translate }}</div>
        @if (recomputed()) {
          @for (p of topAfter(); track p.path; let i = $index) {
            <div class="relative mb-3">
              <img [src]="p.path | thumbnailUrl:512" class="w-full rounded object-cover" [alt]="p.filename" loading="lazy" />
              <span class="absolute top-1 left-1 px-1.5 py-0.5 rounded bg-black/60 text-white text-xs">{{ i + 1 }}</span>
              <span class="absolute bottom-1 right-1 px-1.5 py-0.5 rounded bg-black/60 text-[var(--facet-accent-text)] text-xs font-mono">{{ p.aggregate | fixed:1 }}</span>
            </div>
          }
        } @else {
          <p class="text-xs text-gray-500">{{ 'comparison.top_after_hint' | translate }}</p>
        }
      </div>
    </div>
  `,
})
export class ComparisonSuggestionsTabComponent {
  private readonly api = inject(ApiService);
  private readonly i18n = inject(I18nService);
  private readonly snackBar = inject(MatSnackBar);
  private readonly compareFilters = inject(CompareFiltersService);

  /** Emitted when the user applies the optimized weights — parent syncs the weights tab. */
  readonly weightsApplied = output<Record<string, number>>();

  protected readonly learnedWeights = signal<LearnedWeightsResponse | null>(null);
  protected readonly categoryConfig = signal<CategoryWeights | null>(null);
  protected readonly topBefore = signal<TopPhoto[]>([]);
  protected readonly topAfter = signal<TopPhoto[]>([]);
  protected readonly applied = signal(false);
  protected readonly recomputed = signal(false);
  /** Public so the parent can drive Apply/Recompute from the contextual top bar. */
  readonly saving = signal(false);
  readonly recomputing = signal(false);

  /** A suggestion exists and has not been applied yet. */
  readonly canApply = computed(() => {
    const lw = this.learnedWeights();
    return !!(lw?.available && lw.suggested_weights) && !this.applied();
  });

  /** Weights were applied but the category's scores have not been recomputed. */
  readonly needsRecompute = computed(() => this.applied() && !this.recomputed());

  /** Current vs suggested rows over the category's canonical percent weights. */
  protected readonly weightRows = computed(() => {
    const config = this.categoryConfig();
    if (!config) return [];
    const suggested = this.learnedWeights()?.suggested_weights ?? {};
    return Object.keys(config.weights)
      .filter(k => k.endsWith('_percent'))
      .map(key => {
        const current = config.weights[key] ?? 0;
        const next = key in suggested ? suggested[key] : current;
        return { key, current, suggested: next, changed: next !== current };
      });
  });

  constructor() {
    effect(() => {
      const cat = this.compareFilters.selectedCategory();
      if (cat) void this.loadForCategory(cat);
    });
  }

  private async loadForCategory(category: string): Promise<void> {
    this.applied.set(false);
    this.recomputed.set(false);
    this.topAfter.set([]);
    try {
      const [lw, config, top] = await Promise.all([
        firstValueFrom(this.api.get<LearnedWeightsResponse>('/comparison/learned_weights', { category })),
        firstValueFrom(this.api.get<CategoryWeights>('/comparison/category_weights', { category })),
        this.fetchTopPhotos(category),
      ]);
      this.learnedWeights.set(lw);
      this.categoryConfig.set(config);
      this.topBefore.set(top);
    } catch {
      this.snackBar.open(this.i18n.t('comparison.error_loading_suggestions'), '', { duration: 4000 });
    }
  }

  private async fetchTopPhotos(category: string): Promise<TopPhoto[]> {
    const data = await firstValueFrom(
      this.api.get<{ photos: TopPhoto[] }>('/photos', {
        category, sort: 'aggregate', sort_direction: 'DESC',
        per_page: 10, page: 1, hide_duplicates: true, hide_bursts: true,
      }),
    );
    return data.photos ?? [];
  }

  async applySuggested(): Promise<void> {
    const lw = this.learnedWeights();
    const config = this.categoryConfig();
    const category = this.compareFilters.selectedCategory();
    if (!lw?.suggested_weights || !config || !category) return;
    // Base on the category's canonical weights so only valid keys are saved;
    // learned_weights.current_weights may carry non-canonical keys the config
    // validator would strip.
    const suggested = lw.suggested_weights;
    const merged: Record<string, number> = { ...config.weights };
    for (const key of Object.keys(config.weights)) {
      if (suggested[key] != null) merged[key] = suggested[key];
    }
    this.saving.set(true);
    try {
      await firstValueFrom(this.api.post('/config/update_weights', {
        category, weights: merged, modifiers: config.modifiers, filters: config.filters,
      }));
      this.weightsApplied.emit(merged);
      this.applied.set(true);
      this.snackBar.open(this.i18n.t('comparison.weights_saved'), '', { duration: 3000 });
    } catch {
      this.snackBar.open(this.i18n.t('comparison.error_saving_weights'), '', { duration: 4000 });
    } finally {
      this.saving.set(false);
    }
  }

  async recompute(): Promise<void> {
    const category = this.compareFilters.selectedCategory();
    if (!category) return;
    this.recomputing.set(true);
    try {
      const result = await firstValueFrom(
        this.api.post<{ success: boolean; message?: string }>('/stats/categories/recompute', { category }),
      );
      this.topAfter.set(await this.fetchTopPhotos(category));
      this.recomputed.set(true);
      this.snackBar.open(result.message ?? this.i18n.t('comparison.recalculated'), '', { duration: 5000 });
    } catch {
      this.snackBar.open(this.i18n.t('comparison.error_recalculating'), '', { duration: 4000 });
    } finally {
      this.recomputing.set(false);
    }
  }
}
