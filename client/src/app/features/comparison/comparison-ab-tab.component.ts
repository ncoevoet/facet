import { Component, inject, signal, computed, output } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { MatCardModule } from '@angular/material/card';
import { MatButtonModule } from '@angular/material/button';
import { MatSelectModule } from '@angular/material/select';
import { MatIconModule } from '@angular/material/icon';
import { MatProgressSpinnerModule } from '@angular/material/progress-spinner';
import { MatTooltipModule } from '@angular/material/tooltip';
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

interface PairResponse {
  a?: string;
  b?: string;
  score_a?: number;
  score_b?: number;
  error?: string;
}

interface ComparisonStats {
  total_comparisons: number;
  winner_breakdown: Record<string, number>;
  category_breakdown: { category: string; count: number }[];
  unique_photos_compared: number;
  photos_with_learned_scores: number;
}

interface LearnedWeightsResponse {
  available: boolean;
  message?: string;
  current_weights?: Record<string, number>;
  suggested_weights?: Record<string, number>;
  accuracy_before?: number;
  accuracy_after?: number;
  improvement?: number;
  suggest_changes?: boolean;
  comparisons_used?: number;
  ties_included?: number;
  mispredicted_count?: number;
  category?: string;
}

@Component({
  selector: 'app-comparison-ab-tab',
  standalone: true,
  imports: [
    FormsModule,
    MatCardModule,
    MatButtonModule,
    MatSelectModule,
    MatIconModule,
    MatProgressSpinnerModule,
    MatTooltipModule,
    TranslatePipe,
    FixedPipe,
    ThumbnailUrlPipe,
    WeightLabelKeyPipe,
  ],
  host: { '(window:keydown)': 'onKeydown($event)' },
  template: `
    <div class="mt-4">
      <!-- Strategy selector + keyboard hints -->
      <div class="flex flex-wrap items-center gap-3 mb-4">
        <mat-form-field class="w-56" subscriptSizing="dynamic">
          <mat-label>{{ 'compare.strategy' | translate }}</mat-label>
          <mat-select [value]="strategy()" (selectionChange)="onStrategyChange($event.value)">
            @for (s of strategies; track s) {
              <mat-option [value]="s">{{ ('compare.strategies.' + s) | translate }}</mat-option>
            }
          </mat-select>
        </mat-form-field>
        <button mat-icon-button (click)="showStrategyHelp.set(!showStrategyHelp())"
          [matTooltip]="'compare.tooltips.strategy_info' | translate">
          <mat-icon>help_outline</mat-icon>
        </button>
        <span class="ml-auto text-xs text-gray-500 hidden md:inline">
          {{ 'compare.keyboard.hint' | translate }}
          <kbd class="px-1 rounded bg-neutral-700 text-gray-300">&#8592;</kbd> {{ 'compare.keyboard.left_wins' | translate }} ·
          <kbd class="px-1 rounded bg-neutral-700 text-gray-300">&#8594;</kbd> {{ 'compare.keyboard.right_wins' | translate }} ·
          <kbd class="px-1 rounded bg-neutral-700 text-gray-300">T</kbd> {{ 'compare.keyboard.equal' | translate }} ·
          <kbd class="px-1 rounded bg-neutral-700 text-gray-300">S</kbd> {{ 'compare.keyboard.skip' | translate }}
        </span>
      </div>

      <!-- Strategy help panel -->
      @if (showStrategyHelp()) {
        <mat-card class="mb-4">
          <mat-card-content class="!py-3">
            <div class="grid grid-cols-1 md:grid-cols-2 gap-3 text-sm">
              @for (s of strategies; track s) {
                <div>
                  <div class="font-medium">{{ ('compare.strategy_help.' + s + '_title') | translate }}</div>
                  <div class="text-gray-400 text-xs">{{ ('compare.strategy_help.' + s + '_desc') | translate }}</div>
                </div>
              }
            </div>
          </mat-card-content>
        </mat-card>
      }

      <!-- Photos + stats sidebar -->
      <div class="grid grid-cols-1 lg:grid-cols-[1fr_260px] gap-4">
        <!-- Photo pair -->
        <mat-card>
          <mat-card-content class="!pt-4">
            @if (pairError()) {
              <div class="text-red-400 text-sm mb-4">{{ pairError() }}</div>
            }
            @if (!pairA() && !pairLoading()) {
              <div class="flex flex-col items-center py-8 gap-4">
                <p class="text-sm text-gray-400">{{ 'comparison.compare_description' | translate }}</p>
                <button mat-flat-button (click)="loadNextPair()">
                  <mat-icon>play_arrow</mat-icon>
                  {{ 'comparison.start_comparing' | translate }}
                </button>
              </div>
            } @else if (pairLoading()) {
              <div class="flex justify-center py-8">
                <mat-spinner diameter="40" />
              </div>
            } @else if (pairA() && pairB()) {
              <div class="grid grid-cols-1 md:grid-cols-2 gap-4 mb-4">
                <button
                  class="relative rounded-lg overflow-hidden bg-neutral-900 cursor-pointer border-2 border-transparent hover:border-[var(--mat-sys-primary)] transition-colors text-left p-0"
                  [disabled]="pairSubmitting()"
                  (click)="submitComparison('a')">
                  <img [src]="pairA()! | thumbnailUrl:640" alt="Photo A" class="w-full max-h-[60vh] object-contain" />
                  <div class="absolute top-2 left-2 text-xs font-mono bg-black/60 px-2 py-0.5 rounded">A</div>
                  <div class="absolute bottom-0 inset-x-0 bg-gradient-to-t from-black/80 to-transparent px-3 py-2">
                    <span class="text-sm font-mono text-white">{{ pairScoreA() | fixed:1 }}</span>
                  </div>
                </button>
                <button
                  class="relative rounded-lg overflow-hidden bg-neutral-900 cursor-pointer border-2 border-transparent hover:border-[var(--mat-sys-primary)] transition-colors text-left p-0"
                  [disabled]="pairSubmitting()"
                  (click)="submitComparison('b')">
                  <img [src]="pairB()! | thumbnailUrl:640" alt="Photo B" class="w-full max-h-[60vh] object-contain" />
                  <div class="absolute top-2 right-2 text-xs font-mono bg-black/60 px-2 py-0.5 rounded">B</div>
                  <div class="absolute bottom-0 inset-x-0 bg-gradient-to-t from-black/80 to-transparent px-3 py-2">
                    <span class="text-sm font-mono text-white">{{ pairScoreB() | fixed:1 }}</span>
                  </div>
                </button>
              </div>
              <div class="flex justify-center gap-3">
                <button mat-stroked-button [disabled]="pairSubmitting()" (click)="submitComparison('tie')">
                  <mat-icon>drag_handle</mat-icon>
                  {{ 'comparison.tie' | translate }}
                </button>
                <button mat-stroked-button [disabled]="pairSubmitting()" (click)="loadNextPair()">
                  <mat-icon>skip_next</mat-icon>
                  {{ 'comparison.skip' | translate }}
                </button>
                @if (comparisonCount() > 0) {
                  <span class="flex items-center text-sm text-gray-400 ml-2">
                    {{ comparisonCount() }} {{ 'comparison.comparisons_completed' | translate }}
                  </span>
                }
              </div>
            } @else {
              <div class="text-center py-8 text-gray-400">
                {{ 'comparison.no_more_pairs' | translate }}
              </div>
            }
          </mat-card-content>
        </mat-card>

        <!-- Sidebar: Stats + Weight suggestions -->
        <div class="flex flex-col gap-4">
          <!-- Stats -->
          <mat-card>
            <mat-card-header>
              <mat-card-title class="!text-sm">{{ 'compare.stats.title' | translate }}</mat-card-title>
            </mat-card-header>
            <mat-card-content class="!pt-2">
              @if (comparisonStats(); as stats) {
                <div class="grid grid-cols-2 gap-x-3 gap-y-1 text-sm">
                  <span class="text-gray-400">{{ 'compare.stats.total_comparisons' | translate }}</span>
                  <span class="text-right font-mono">{{ stats.total_comparisons }}</span>
                  <span class="text-gray-400">{{ 'compare.stats.a_wins' | translate }}</span>
                  <span class="text-right font-mono">{{ stats.winner_breakdown['a'] || 0 }}</span>
                  <span class="text-gray-400">{{ 'compare.stats.b_wins' | translate }}</span>
                  <span class="text-right font-mono">{{ stats.winner_breakdown['b'] || 0 }}</span>
                  <span class="text-gray-400">{{ 'compare.stats.ties_label' | translate }}</span>
                  <span class="text-right font-mono">{{ stats.winner_breakdown['tie'] || 0 }}</span>
                </div>
              } @else {
                <p class="text-xs text-gray-500">{{ 'comparison.no_data_yet' | translate }}</p>
              }
            </mat-card-content>
          </mat-card>

          <!-- Weight Suggestions -->
          <mat-card>
            <mat-card-header>
              <mat-card-title class="!text-sm">{{ 'compare.actions.suggest_weights' | translate }}</mat-card-title>
            </mat-card-header>
            <mat-card-content class="!pt-2">
              <button mat-stroked-button class="w-full mb-3" [disabled]="learnedWeightsLoading()"
                (click)="loadLearnedWeights()">
                @if (learnedWeightsLoading()) {
                  <mat-spinner diameter="16" />
                }
                {{ 'compare.actions.suggest_weights' | translate }}
              </button>
              @if (learnedWeights(); as lw) {
                @if (lw.available) {
                  <div class="text-xs space-y-2">
                    <div class="text-gray-400">
                      {{ 'compare.weights.learned_from' | translate:{ count: lw.comparisons_used ?? 0 } }}
                      @if (lw.ties_included) {
                        ({{ 'compare.weights.incl_ties' | translate:{ count: lw.ties_included } }})
                      }
                    </div>
                    <div class="flex items-center gap-2">
                      <span class="text-gray-400">{{ 'compare.weights.prediction_accuracy' | translate }}:</span>
                      <span class="font-mono">{{ (lw.accuracy_before ?? 0) | fixed:0 }}%</span>
                      <span class="text-gray-500">&rarr;</span>
                      <span class="font-mono text-[var(--facet-accent-text)]">{{ (lw.accuracy_after ?? 0) | fixed:0 }}%</span>
                    </div>
                    @if (lw.mispredicted_count) {
                      <div class="text-gray-500">
                        {{ 'compare.weights.mispredicted' | translate:{ count: lw.mispredicted_count } }}
                      </div>
                    }
                    @if (lw.suggest_changes && lw.suggested_weights) {
                      <div class="space-y-0.5 mb-3">
                        @for (key of currentWeightKeys(); track key) {
                          <div class="flex items-center text-xs">
                            <span class="w-28 shrink-0 truncate text-gray-400">{{ key | weightLabelKey | translate }}</span>
                            <span class="font-mono w-10 shrink-0 text-right tabular-nums">{{ lw.current_weights?.[key] || 0 }}</span>
                            <span class="w-6 shrink-0 text-center text-gray-500">&rarr;</span>
                            <span class="font-mono w-10 shrink-0 text-right tabular-nums text-[var(--facet-accent-text)]">{{ lw.suggested_weights[key] || 0 }}</span>
                          </div>
                        }
                      </div>
                      <button mat-flat-button class="w-full" [disabled]="!auth.isEdition()" (click)="applyWeights()">
                        <mat-icon>auto_fix_high</mat-icon>
                        {{ 'comparison.apply_suggested' | translate }}
                      </button>
                    } @else {
                      <p class="text-amber-400">{{ 'compare.weights.already_good' | translate }}</p>
                    }
                  </div>
                } @else {
                  <p class="text-xs text-gray-500">{{ lw.message }}</p>
                }
              }
            </mat-card-content>
          </mat-card>
        </div>
      </div>
    </div>
  `,
})
export class ComparisonAbTabComponent {
  private api = inject(ApiService);
  private i18n = inject(I18nService);
  private snackBar = inject(MatSnackBar);
  readonly auth = inject(AuthService);
  private compareFilters = inject(CompareFiltersService);

  /** Emitted when user applies learned weight suggestions — parent updates the weights tab */
  readonly weightsApplied = output<Record<string, number>>();

  readonly strategies = ['uncertainty', 'boundary', 'active', 'random'] as const;

  pairA = signal<string | null>(null);
  pairB = signal<string | null>(null);
  pairScoreA = signal(0);
  pairScoreB = signal(0);
  pairLoading = signal(false);
  pairSubmitting = signal(false);
  pairError = signal<string | null>(null);
  comparisonCount = signal(0);
  strategy = signal<string>('uncertainty');
  comparisonStats = signal<ComparisonStats | null>(null);
  learnedWeights = signal<LearnedWeightsResponse | null>(null);
  learnedWeightsLoading = signal(false);
  showStrategyHelp = signal(false);

  currentWeightKeys = computed(() =>
    Object.keys(this.learnedWeights()?.current_weights ?? {}).filter(k => k.endsWith('_percent')),
  );

  onStrategyChange(value: string): void {
    this.strategy.set(value);
    if (this.pairA()) void this.loadNextPair();
  }

  async loadNextPair(): Promise<void> {
    const cat = this.compareFilters.selectedCategory();
    if (!cat) return;

    this.pairLoading.set(true);
    this.pairError.set(null);
    void this.loadComparisonStats();
    try {
      const data = await firstValueFrom(
        this.api.get<PairResponse>('/comparison/next_pair', { category: cat, strategy: this.strategy() }),
      );
      if (data.error) {
        this.pairA.set(null);
        this.pairB.set(null);
        this.pairError.set(data.error);
      } else if (data.a && data.b) {
        this.pairA.set(data.a);
        this.pairB.set(data.b);
        this.pairScoreA.set(data.score_a ?? 0);
        this.pairScoreB.set(data.score_b ?? 0);
      } else {
        this.pairA.set(null);
        this.pairB.set(null);
        this.pairError.set(this.i18n.t('comparison.no_more_pairs'));
      }
    } catch {
      this.pairError.set(this.i18n.t('comparison.error_loading_pair'));
    } finally {
      this.pairLoading.set(false);
    }
  }

  async submitComparison(winner: 'a' | 'b' | 'tie'): Promise<void> {
    const a = this.pairA();
    const b = this.pairB();
    const cat = this.compareFilters.selectedCategory();
    if (!a || !b || !cat) return;

    this.pairSubmitting.set(true);
    try {
      await firstValueFrom(
        this.api.post('/comparison/submit', { photo_a: a, photo_b: b, winner, category: cat }),
      );
      this.comparisonCount.update(c => c + 1);
      void this.loadComparisonStats();
      await this.loadNextPair();
    } catch {
      this.pairError.set(this.i18n.t('comparison.error_submitting'));
    } finally {
      this.pairSubmitting.set(false);
    }
  }

  async loadComparisonStats(): Promise<void> {
    try {
      const data = await firstValueFrom(this.api.get<ComparisonStats>('/comparison/stats'));
      this.comparisonStats.set(data);
    } catch { /* non-critical */ }
  }

  async loadLearnedWeights(): Promise<void> {
    const cat = this.compareFilters.selectedCategory();
    if (!cat) return;
    this.learnedWeightsLoading.set(true);
    try {
      const data = await firstValueFrom(
        this.api.get<LearnedWeightsResponse>('/comparison/learned_weights', { category: cat }),
      );
      this.learnedWeights.set(data);
    } catch {
      this.snackBar.open(this.i18n.t('comparison.error_loading_suggestions'), '', { duration: 4000 });
    } finally {
      this.learnedWeightsLoading.set(false);
    }
  }

  applyWeights(): void {
    const lw = this.learnedWeights();
    if (!lw?.suggested_weights) return;
    const merged = { ...(lw.current_weights ?? {}), ...lw.suggested_weights };
    this.weightsApplied.emit(merged);
    this.snackBar.open(this.i18n.t('comparison.optimized'), '', { duration: 3000 });
  }

  onKeydown(event: KeyboardEvent): void {
    const tag = (event.target as HTMLElement)?.tagName;
    if (tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT') return;
    if (!this.pairA() || !this.pairB() || this.pairSubmitting() || this.pairLoading()) return;
    switch (event.key) {
      case 'ArrowLeft': void this.submitComparison('a'); event.preventDefault(); break;
      case 'ArrowRight': void this.submitComparison('b'); event.preventDefault(); break;
      case 't': case 'T': void this.submitComparison('tie'); event.preventDefault(); break;
      case 's': case 'S': void this.loadNextPair(); event.preventDefault(); break;
    }
  }
}
