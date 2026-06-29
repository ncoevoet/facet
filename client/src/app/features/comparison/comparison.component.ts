import { Component, computed, DestroyRef, effect, inject, signal, viewChild, TemplateRef } from '@angular/core';
import { NgTemplateOutlet } from '@angular/common';
import { MatIconModule } from '@angular/material/icon';
import { MatButtonModule } from '@angular/material/button';
import { MatTabsModule } from '@angular/material/tabs';
import { MatProgressSpinnerModule } from '@angular/material/progress-spinner';
import { MatTooltipModule } from '@angular/material/tooltip';
import { firstValueFrom } from 'rxjs';
import { Chart, registerables } from 'chart.js';
import { ApiService } from '../../core/services/api.service';
import { AuthService } from '../../core/services/auth.service';
import { ThemeService } from '../../core/services/theme.service';
import { PageHelpService } from '../../core/services/page-help.service';
import { GalleryStore } from '../gallery/gallery.store';
import { HeaderSlotService } from '../../core/services/header-slot.service';
import { TranslatePipe } from '../../shared/pipes/translate.pipe';
import { CompareFiltersService } from './compare-filters.service';
import { ComparisonWeightsTabComponent } from './comparison-weights-tab.component';
import { ComparisonSnapshotsTabComponent } from './comparison-snapshots-tab.component';
import { ComparisonAbTabComponent } from './comparison-ab-tab.component';
import { ComparisonSuggestionsTabComponent } from './comparison-suggestions-tab.component';
import { I18N } from '../../core/i18n/keys';

Chart.register(...registerables);

@Component({
  selector: 'app-comparison',
  imports: [
    NgTemplateOutlet,
    MatIconModule,
    MatButtonModule,
    MatTabsModule,
    MatProgressSpinnerModule,
    MatTooltipModule,
    TranslatePipe,
    ComparisonWeightsTabComponent,
    ComparisonSnapshotsTabComponent,
    ComparisonAbTabComponent,
    ComparisonSuggestionsTabComponent,
  ],
  template: `
    <div class="p-4 md:p-6 max-w-screen-2xl mx-auto">
      <!-- Tab-contextual actions projected into the global header on lg (HeaderSlotService);
           small screens use the in-page Top bar below and the weights-tab mobile bar. -->
      <ng-template #compareToolbar>
        <div class="flex items-center gap-1">
          @if (selectedTabIndex() === 3) {
            <ng-container *ngTemplateOutlet="weightsTab()?.weightsActionsTpl() ?? null" />
          }
          @if (selectedTabIndex() === 2) {
            <button mat-icon-button
              [disabled]="!suggestionsTab()?.canApply() || (suggestionsTab()?.saving() ?? false) || !auth.isEdition()"
              (click)="suggestionsTab()?.applySuggested()"
              [matTooltip]="I18N.comparison.apply_suggested | translate"
              [attr.aria-label]="I18N.comparison.apply_suggested | translate">
              @if (suggestionsTab()?.saving()) {
                <mat-spinner diameter="20" />
              } @else {
                <mat-icon>auto_fix_high</mat-icon>
              }
            </button>
            @if (suggestionsTab()?.needsRecompute()) {
              <button mat-icon-button
                [disabled]="(suggestionsTab()?.recomputing() ?? false) || !auth.isEdition()"
                (click)="suggestionsTab()?.recompute()"
                [matTooltip]="I18N.comparison.recompute_category | translate"
                [attr.aria-label]="I18N.comparison.recompute_category | translate">
                @if (suggestionsTab()?.recomputing()) {
                  <mat-spinner diameter="20" />
                } @else {
                  <mat-icon>calculate</mat-icon>
                }
              </button>
            }
          }
        </div>
      </ng-template>

      <!-- Top bar: actions contextual to the active tab (small screens; lg uses the header slot) -->
      @if (showTopActions()) {
        <div class="lg:hidden flex flex-wrap items-center gap-3 mb-4 md:mb-6">
          <div class="flex gap-2 ml-auto flex-wrap">
            @if (selectedTabIndex() === 2) {
              <!-- Weight Suggestions tab -->
              @if (suggestionsTab()?.canApply()) {
                <button mat-flat-button
                  [disabled]="(suggestionsTab()?.saving() ?? false) || !auth.isEdition()"
                  (click)="suggestionsTab()?.applySuggested()">
                  <span class="inline-flex items-center gap-1.5">
                    @if (suggestionsTab()?.saving()) {
                      <mat-spinner diameter="16" class="!w-4 !h-4" />
                    } @else {
                      <mat-icon class="!m-0">auto_fix_high</mat-icon>
                    }
                    {{ I18N.comparison.apply_suggested | translate }}
                  </span>
                </button>
              }
              @if (suggestionsTab()?.needsRecompute()) {
                <button mat-stroked-button
                  [disabled]="(suggestionsTab()?.recomputing() ?? false) || !auth.isEdition()"
                  (click)="suggestionsTab()?.recompute()">
                  <span class="inline-flex items-center gap-1.5">
                    @if (suggestionsTab()?.recomputing()) {
                      <mat-spinner diameter="16" class="!w-4 !h-4" />
                    } @else {
                      <mat-icon class="!m-0">calculate</mat-icon>
                    }
                    {{ I18N.comparison.recompute_category | translate }}
                  </span>
                </button>
              }
            }
          </div>
        </div>
      }

      @if (compareFilters.selectedCategory()) {
        <mat-tab-group class="mb-6" [selectedIndex]="0" (selectedIndexChange)="onTabChange($event)">
          <!-- Snapshots tab -->
          <mat-tab>
            <ng-template mat-tab-label>
              <mat-icon class="mr-2">bookmark</mat-icon>
              {{ I18N.comparison.snapshots | translate }}
            </ng-template>
            <app-comparison-snapshots-tab #snapshotsTabEl (restored)="weightsTab()?.loadWeights()" />
          </mat-tab>

          <!-- A/B Compare tab -->
          <mat-tab>
            <ng-template mat-tab-label>
              <mat-icon class="mr-2">compare</mat-icon>
              {{ I18N.comparison.compare_tab | translate }}
            </ng-template>
            <app-comparison-ab-tab #abTabEl (weightsApplied)="onWeightsApplied($event)" />
          </mat-tab>

          <!-- Weight Suggestions tab (enabled once enough comparisons exist) -->
          <mat-tab [disabled]="weightsLocked()">
            <ng-template mat-tab-label>
              <span [matTooltip]="weightsLocked() ? ((I18N.comparison.suggestions_locked_tooltip | translate:{ count: weightsRemaining() })) : ''"
                    class="inline-flex items-center">
                <mat-icon class="mr-2">auto_fix_high</mat-icon>
                {{ I18N.comparison.suggestions_tab | translate }}
              </span>
            </ng-template>
            <app-comparison-suggestions-tab #suggestionsTabEl (weightsApplied)="onWeightsApplied($event)" />
          </mat-tab>

          <!-- Weights tab -->
          <mat-tab>
            <ng-template mat-tab-label>
              <mat-icon class="mr-2">tune</mat-icon>
              {{ I18N.comparison.weights | translate }}
            </ng-template>
            <app-comparison-weights-tab #weightsTabEl />
          </mat-tab>
        </mat-tab-group>
      }
    </div>
  `,
})
export class ComparisonComponent {
  protected readonly I18N = I18N;
  protected readonly auth = inject(AuthService);
  private readonly api = inject(ApiService);
  private readonly store = inject(GalleryStore);
  private readonly themeService = inject(ThemeService);
  protected readonly compareFilters = inject(CompareFiltersService);
  private readonly pageHelp = inject(PageHelpService);
  private readonly headerSlot = inject(HeaderSlotService);

  protected readonly weightsTab = viewChild<ComparisonWeightsTabComponent>('weightsTabEl');
  protected readonly snapshotsTab = viewChild<ComparisonSnapshotsTabComponent>('snapshotsTabEl');
  protected readonly abTab = viewChild<ComparisonAbTabComponent>('abTabEl');
  protected readonly suggestionsTab = viewChild<ComparisonSuggestionsTabComponent>('suggestionsTabEl');
  protected readonly compareToolbar = viewChild<TemplateRef<unknown>>('compareToolbar');

  /** Active tab (0 Snapshots, 1 Compare, 2 Suggestions, 3 Weights) — drives the contextual top bar. */
  protected readonly selectedTabIndex = signal(0);

  /** Total comparisons (all sources) + threshold, to gate the Weight Suggestions tab. */
  private readonly comparisonStats = signal<{ total_comparisons: number; min_comparisons_for_optimization?: number } | null>(null);
  private readonly threshold = computed(() => this.comparisonStats()?.min_comparisons_for_optimization ?? 50);
  protected readonly weightsRemaining = computed(() => Math.max(0, this.threshold() - (this.comparisonStats()?.total_comparisons ?? 0)));
  protected readonly weightsLocked = computed(() => (this.comparisonStats()?.total_comparisons ?? 0) < this.threshold());

  /** Whether the contextual top bar has any action to show for the active tab. */
  protected readonly showTopActions = computed(() => {
    const i = this.selectedTabIndex();
    if (i === 2) return !!(this.suggestionsTab()?.canApply() || this.suggestionsTab()?.needsRecompute());
    return false;
  });

  constructor() {
    this.pageHelp.setDescription(I18N.compare.help);
    inject(DestroyRef).onDestroy(() => {
      this.pageHelp.setDescription(null);
      const tpl = this.compareToolbar();
      if (tpl) this.headerSlot.clear(tpl);
    });
    effect(() => {
      const dark = this.themeService.darkMode();
      Chart.defaults.color = dark ? '#a3a3a3' : '#525252';
      Chart.defaults.borderColor = dark ? '#262626' : '#e5e5e5';
    });
    effect(() => {
      const tpl = this.compareToolbar();
      if (tpl) this.headerSlot.set(tpl);
    });
    void this.loadCategories();
    void this.loadComparisonStats();
  }

  private async loadComparisonStats(): Promise<void> {
    try {
      const stats = await firstValueFrom(
        this.api.get<{ total_comparisons: number; min_comparisons_for_optimization?: number }>('/comparison/stats'),
      );
      this.comparisonStats.set(stats);
    } catch { /* non-critical: the tab simply stays locked */ }
  }

  private async loadCategories(): Promise<void> {
    try {
      if (this.store.types().length === 0) {
        await this.store.loadTypeCounts();
      }
      const types = this.store.types();
      if (types.length > 0 && !this.compareFilters.selectedCategory()) {
        this.compareFilters.selectedCategory.set(types[0].id);
      }
    } catch { /* non-critical */ }
  }

  protected onTabChange(index: number): void {
    this.selectedTabIndex.set(index);
    if (index === 1 && !this.abTab()?.pairA() && !this.abTab()?.pairLoading()) {
      void this.abTab()?.loadNextPair();
    }
  }

  protected onWeightsApplied(merged: Record<string, number>): void {
    const tab = this.weightsTab();
    if (tab) tab.weights.set(merged);
  }
}
