import { Component, effect, inject, input, signal } from '@angular/core';
import { MatCardModule } from '@angular/material/card';
import { MatButtonModule } from '@angular/material/button';
import { MatIconModule } from '@angular/material/icon';
import { MatProgressSpinnerModule } from '@angular/material/progress-spinner';
import { firstValueFrom } from 'rxjs';
import { ApiService } from '../../core/services/api.service';
import { TranslatePipe } from '../../shared/pipes/translate.pipe';
import { I18N_KEYS } from '../../core/i18n/keys';

interface FilterConflict {
  type: string;
  filter: string;
  required?: unknown;
  actual?: unknown;
  missing?: string[];
  excluded?: string[];
  found?: string[];
  message: string;
}

interface FilterSuggestion {
  type: string;
  filter: string;
  current?: unknown;
  suggested?: unknown;
  to_remove?: string[];
  message: string;
}

interface SuggestFiltersResponse {
  current_category?: string | null;
  target_category?: string | null;
  target_filters?: Record<string, unknown>;
  conflicts?: FilterConflict[];
  suggestions?: FilterSuggestion[];
  photo_values?: Record<string, unknown>;
  no_conflicts?: boolean;
  message?: string;
}

/**
 * Reusable "why isn't this photo <category>?" panel. Given a photo path and a
 * target category, calls `POST /api/comparison/suggest_filters` and renders
 * the blocking filters plus the exact threshold changes that would resolve
 * them. Designed to be dropped into the lightbox/critique surface.
 */
@Component({
  selector: 'app-category-explainer',
  standalone: true,
  imports: [MatCardModule, MatButtonModule, MatIconModule, MatProgressSpinnerModule, TranslatePipe],
  template: `
    <mat-card>
      <mat-card-header>
        <mat-card-title>{{ I18N.comparison.context.explainer_title | translate }}</mat-card-title>
        <mat-card-subtitle>
          {{ I18N.comparison.context.explainer_subtitle | translate }}:
          {{ ('category_names.' + targetCategory()) | translate }}
        </mat-card-subtitle>
      </mat-card-header>
      <mat-card-content class="!pt-4">
        @if (loading()) {
          <div class="flex justify-center py-6"><mat-spinner diameter="28" [attr.aria-label]="I18N.ui.labels.loading | translate" /></div>
        } @else if (error()) {
          <div class="flex items-center gap-2 text-sm text-red-400">
            <mat-icon class="!text-base !w-4 !h-4">error_outline</mat-icon>
            {{ I18N.comparison.context.explainer_error | translate }}
          </div>
          <button mat-button class="!mt-2" (click)="retry()">
            <mat-icon>refresh</mat-icon>
            {{ I18N.comparison.reset | translate }}
          </button>
        } @else if (result(); as r) {
          @if (r.current_category) {
            <div class="flex items-center gap-2 text-sm mb-3">
              <span class="text-gray-400">{{ I18N.comparison.context.explainer_current_category | translate }}:</span>
              <span class="font-medium">{{ ('category_names.' + r.current_category) | translate }}</span>
            </div>
          }

          @if (r.current_category && r.current_category === r.target_category) {
            <div class="flex items-center gap-2 text-sm text-green-400">
              <mat-icon class="!text-base !w-4 !h-4">check_circle</mat-icon>
              {{ I18N.comparison.context.explainer_already_in_category | translate }}
            </div>
          } @else if (r.no_conflicts) {
            <div class="flex items-center gap-2 text-sm text-green-400">
              <mat-icon class="!text-base !w-4 !h-4">check_circle</mat-icon>
              {{ I18N.comparison.context.explainer_no_conflicts | translate }}
            </div>
          } @else {
            <div class="mb-4">
              <h4 class="text-xs uppercase tracking-wide text-gray-500 mb-2">
                {{ I18N.comparison.context.explainer_conflicts_title | translate }}
              </h4>
              <ul class="flex flex-col gap-1.5">
                @for (c of r.conflicts; track c.type + c.filter) {
                  <li class="flex items-start gap-2 text-sm">
                    <mat-icon class="!text-base !w-4 !h-4 text-amber-400 shrink-0 mt-0.5">block</mat-icon>
                    <span>{{ c.message }}</span>
                  </li>
                }
              </ul>
            </div>
            @if ((r.suggestions?.length ?? 0) > 0) {
              <div>
                <h4 class="text-xs uppercase tracking-wide text-gray-500 mb-2">
                  {{ I18N.comparison.context.explainer_suggestions_title | translate }}
                </h4>
                <ul class="flex flex-col gap-1.5">
                  @for (s of r.suggestions; track s.type + s.filter) {
                    <li class="flex items-start gap-2 text-sm">
                      <mat-icon class="!text-base !w-4 !h-4 text-blue-400 shrink-0 mt-0.5">lightbulb</mat-icon>
                      <span>{{ s.message }}</span>
                    </li>
                  }
                </ul>
              </div>
            }
          }
        }
      </mat-card-content>
    </mat-card>
  `,
})
export class ComparisonCategoryExplainerComponent {
  protected readonly I18N = I18N_KEYS;
  private readonly api = inject(ApiService);

  readonly path = input.required<string>();
  readonly targetCategory = input.required<string>();

  readonly loading = signal(false);
  readonly error = signal(false);
  readonly result = signal<SuggestFiltersResponse | null>(null);

  constructor() {
    effect(() => {
      const path = this.path();
      const targetCategory = this.targetCategory();
      void this.load(path, targetCategory);
    });
  }

  retry(): void {
    void this.load(this.path(), this.targetCategory());
  }

  private async load(path: string, targetCategory: string): Promise<void> {
    if (!path || !targetCategory) {
      this.result.set(null);
      return;
    }
    this.loading.set(true);
    this.error.set(false);
    const isStale = () => this.path() !== path || this.targetCategory() !== targetCategory;
    try {
      const data = await firstValueFrom(
        this.api.post<SuggestFiltersResponse>('/comparison/suggest_filters', { path, target_category: targetCategory }),
      );
      if (isStale()) return;
      this.result.set(data);
    } catch {
      if (isStale()) return;
      this.error.set(true);
      this.result.set(null);
    } finally {
      if (!isStale()) this.loading.set(false);
    }
  }
}
