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
  mispredicted_count?: number;
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
    WeightLabelKeyPipe,
  ],
  template: `
    <div class="max-w-2xl pt-2">
      @if (loading()) {
        <div class="flex justify-center py-10"><mat-spinner diameter="32" /></div>
      } @else if (learnedWeights(); as lw) {
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
              <div class="space-y-0.5">
                @for (key of currentWeightKeys(); track key) {
                  <div class="flex items-center text-xs">
                    <span class="w-32 shrink-0 truncate text-gray-400">{{ key | weightLabelKey | translate }}</span>
                    <span class="font-mono w-10 shrink-0 text-right tabular-nums">{{ lw.current_weights?.[key] || 0 }}</span>
                    <span class="w-6 shrink-0 text-center text-gray-500">&rarr;</span>
                    <span class="font-mono w-10 shrink-0 text-right tabular-nums text-[var(--facet-accent-text)]">{{ lw.suggested_weights[key] || 0 }}</span>
                  </div>
                }
              </div>
              <button mat-flat-button [disabled]="!auth.isEdition()" (click)="applyWeights()">
                <mat-icon>auto_fix_high</mat-icon>
                {{ 'comparison.apply_suggested' | translate }}
              </button>
            </mat-card-content>
          </mat-card>
        } @else if (lw.available) {
          <p class="text-amber-400 text-sm">{{ 'compare.weights.already_good' | translate }}</p>
        } @else {
          <p class="text-sm text-gray-500">{{ lw.message }}</p>
        }
      }
    </div>
  `,
})
export class ComparisonSuggestionsTabComponent {
  private readonly api = inject(ApiService);
  protected readonly auth = inject(AuthService);
  private readonly i18n = inject(I18nService);
  private readonly snackBar = inject(MatSnackBar);
  private readonly compareFilters = inject(CompareFiltersService);

  /** Emitted when the user applies the optimized weights — parent updates the weights tab. */
  readonly weightsApplied = output<Record<string, number>>();

  protected readonly learnedWeights = signal<LearnedWeightsResponse | null>(null);
  protected readonly loading = signal(false);

  protected readonly currentWeightKeys = computed(() =>
    Object.keys(this.learnedWeights()?.current_weights ?? {}).filter(k => k.endsWith('_percent')),
  );

  constructor() {
    effect(() => {
      const cat = this.compareFilters.selectedCategory();
      if (cat) void this.loadLearnedWeights(cat);
    });
  }

  private async loadLearnedWeights(category: string): Promise<void> {
    this.loading.set(true);
    try {
      const data = await firstValueFrom(
        this.api.get<LearnedWeightsResponse>('/comparison/learned_weights', { category }),
      );
      this.learnedWeights.set(data);
    } catch {
      this.snackBar.open(this.i18n.t('comparison.error_loading_suggestions'), '', { duration: 4000 });
    } finally {
      this.loading.set(false);
    }
  }

  protected applyWeights(): void {
    const lw = this.learnedWeights();
    if (!lw?.suggested_weights) return;
    const merged = { ...(lw.current_weights ?? {}), ...lw.suggested_weights };
    this.weightsApplied.emit(merged);
    this.snackBar.open(this.i18n.t('comparison.optimized'), '', { duration: 3000 });
  }
}
