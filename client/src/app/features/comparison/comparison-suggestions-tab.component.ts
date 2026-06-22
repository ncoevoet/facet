import { Component, inject, signal, computed, effect, output } from '@angular/core';
import { MatCardModule } from '@angular/material/card';
import { MatButtonModule } from '@angular/material/button';
import { MatIconModule } from '@angular/material/icon';
import { MatProgressSpinnerModule } from '@angular/material/progress-spinner';
import { MatSnackBar } from '@angular/material/snack-bar';
import { firstValueFrom } from 'rxjs';
import { ApiService } from '../../core/services/api.service';
import { AuthService } from '../../core/services/auth.service';
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
    MatCardModule,
    MatButtonModule,
    MatIconModule,
    MatProgressSpinnerModule,
    TranslatePipe,
    FixedPipe,
    ThumbnailUrlPipe,
    WeightLabelKeyPipe,
  ],
  template: `
    <div class="pt-2 space-y-4">
      @if (learnedWeights(); as lw) {
        @if (lw.available && lw.suggest_changes && lw.suggested_weights) {
          <mat-card>
            <mat-card-content class="!pt-4 text-sm space-y-3">
              <div class="text-gray-400">
                {{ 'compare.weights.learned_from' | translate:{ count: lw.comparisons_used ?? 0 } }}
              </div>
              <div class="flex items-center gap-2">
                <span class="text-gray-400">{{ 'compare.weights.prediction_accuracy' | translate }}:</span>
                <span class="font-mono">{{ (lw.accuracy_before ?? 0) | fixed:0 }}%</span>
                <span class="text-gray-500">&rarr;</span>
                <span class="font-mono text-[var(--facet-accent-text)]">{{ (lw.accuracy_after ?? 0) | fixed:0 }}%</span>
              </div>
              <div class="text-xs max-w-md">
                <div class="flex items-center gap-2 pb-1 mb-1 border-b border-[var(--mat-sys-outline-variant)] text-gray-500 uppercase text-[10px] font-semibold tracking-wide">
                  <span class="flex-1">{{ 'comparison.weight_property' | translate }}</span>
                  <span class="w-14 text-right">{{ 'comparison.weight_current' | translate }}</span>
                  <span class="w-5 shrink-0"></span>
                  <span class="w-14 text-right">{{ 'comparison.weight_suggested' | translate }}</span>
                </div>
                @for (key of currentWeightKeys(); track key) {
                  <div class="flex items-center gap-2 py-1 border-b border-[var(--mat-sys-outline-variant)]"
                       [class.font-semibold]="(lw.suggested_weights[key] || 0) !== (lw.current_weights?.[key] || 0)">
                    <span class="flex-1 truncate text-gray-400">{{ key | weightLabelKey | translate }}</span>
                    <span class="font-mono w-14 text-right tabular-nums">{{ lw.current_weights?.[key] || 0 }}</span>
                    <mat-icon class="!w-5 !h-5 !text-lg !leading-5 text-gray-500 shrink-0">arrow_forward</mat-icon>
                    <span class="font-mono w-14 text-right tabular-nums text-[var(--facet-accent-text)]">{{ lw.suggested_weights[key] || 0 }}</span>
                  </div>
                }
              </div>
              <div class="flex flex-wrap gap-2">
                <button mat-flat-button [disabled]="applied() || saving() || !auth.isEdition()" (click)="applySuggested()">
                  @if (saving()) {
                    <mat-spinner diameter="16" class="inline-flex !w-4 !h-4" />
                  } @else {
                    <mat-icon>auto_fix_high</mat-icon>
                  }
                  {{ 'comparison.apply_suggested' | translate }}
                </button>
                @if (applied() && !recomputed()) {
                  <button mat-stroked-button [disabled]="recomputing() || !auth.isEdition()" (click)="recompute()">
                    @if (recomputing()) {
                      <mat-spinner diameter="16" class="inline-flex !w-4 !h-4" />
                    } @else {
                      <mat-icon>calculate</mat-icon>
                    }
                    {{ 'comparison.recompute_category' | translate }}
                  </button>
                }
              </div>
              @if (applied() && !recomputed()) {
                <p class="text-amber-400 text-xs">{{ 'comparison.recompute_needed' | translate }}</p>
              }
            </mat-card-content>
          </mat-card>
        } @else if (lw.available) {
          <p class="text-amber-400 text-sm">{{ 'compare.weights.already_good' | translate }}</p>
        } @else {
          <p class="text-sm text-gray-500">{{ lw.message }}</p>
        }
      }

      <!-- Before / after top photos -->
      <div class="grid grid-cols-2 gap-4">
        <div>
          <div class="text-xs font-semibold uppercase opacity-60 mb-2">{{ 'comparison.top_before' | translate }}</div>
          @for (p of topBefore(); track p.path; let i = $index) {
            <div class="flex items-center gap-2 mb-1">
              <span class="text-xs w-5 text-right text-gray-500">{{ i + 1 }}</span>
              <img [src]="p.path | thumbnailUrl:96" class="w-12 h-12 rounded object-cover" [alt]="p.filename" loading="lazy" />
              <span class="font-mono text-xs">{{ p.aggregate | fixed:1 }}</span>
            </div>
          }
        </div>
        <div>
          <div class="text-xs font-semibold uppercase opacity-60 mb-2">{{ 'comparison.top_after' | translate }}</div>
          @if (recomputed()) {
            @for (p of topAfter(); track p.path; let i = $index) {
              <div class="flex items-center gap-2 mb-1">
                <span class="text-xs w-5 text-right text-gray-500">{{ i + 1 }}</span>
                <img [src]="p.path | thumbnailUrl:96" class="w-12 h-12 rounded object-cover" [alt]="p.filename" loading="lazy" />
                <span class="font-mono text-xs text-[var(--facet-accent-text)]">{{ p.aggregate | fixed:1 }}</span>
              </div>
            }
          } @else {
            <p class="text-xs text-gray-500">{{ 'comparison.top_after_hint' | translate }}</p>
          }
        </div>
      </div>
    </div>
  `,
})
export class ComparisonSuggestionsTabComponent {
  private readonly api = inject(ApiService);
  protected readonly auth = inject(AuthService);
  private readonly i18n = inject(I18nService);
  private readonly snackBar = inject(MatSnackBar);
  private readonly compareFilters = inject(CompareFiltersService);

  /** Emitted when the user applies the optimized weights — parent syncs the weights tab. */
  readonly weightsApplied = output<Record<string, number>>();

  protected readonly learnedWeights = signal<LearnedWeightsResponse | null>(null);
  private readonly categoryConfig = signal<CategoryWeights | null>(null);
  protected readonly topBefore = signal<TopPhoto[]>([]);
  protected readonly topAfter = signal<TopPhoto[]>([]);
  protected readonly applied = signal(false);
  protected readonly recomputed = signal(false);
  protected readonly saving = signal(false);
  protected readonly recomputing = signal(false);

  protected readonly currentWeightKeys = computed(() =>
    Object.keys(this.learnedWeights()?.current_weights ?? {}).filter(k => k.endsWith('_percent')),
  );

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

  protected async applySuggested(): Promise<void> {
    const lw = this.learnedWeights();
    const config = this.categoryConfig();
    const category = this.compareFilters.selectedCategory();
    if (!lw?.suggested_weights || !config || !category) return;
    const merged = { ...(lw.current_weights ?? {}), ...lw.suggested_weights };
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

  protected async recompute(): Promise<void> {
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
