import { Component, inject, viewChild } from '@angular/core';
import { MatIconModule } from '@angular/material/icon';
import { MatButtonModule } from '@angular/material/button';
import { MatTabsModule } from '@angular/material/tabs';
import { MatProgressSpinnerModule } from '@angular/material/progress-spinner';
import { MatTooltipModule } from '@angular/material/tooltip';
import { Chart, registerables } from 'chart.js';
import { AuthService } from '../../core/services/auth.service';
import { GalleryStore } from '../gallery/gallery.store';
import { TranslatePipe } from '../../shared/pipes/translate.pipe';
import { CompareFiltersService } from './compare-filters.service';
import { ComparisonWeightsTabComponent } from './comparison-weights-tab.component';
import { ComparisonSnapshotsTabComponent } from './comparison-snapshots-tab.component';
import { ComparisonAbTabComponent } from './comparison-ab-tab.component';

Chart.register(...registerables);
Chart.defaults.color = '#a3a3a3';
Chart.defaults.borderColor = '#262626';

@Component({
  selector: 'app-comparison',
  imports: [
    MatIconModule,
    MatButtonModule,
    MatTabsModule,
    MatProgressSpinnerModule,
    MatTooltipModule,
    TranslatePipe,
    ComparisonWeightsTabComponent,
    ComparisonSnapshotsTabComponent,
    ComparisonAbTabComponent,
  ],
  template: `
    <div class="p-4 md:p-6 max-w-7xl mx-auto">
      <h1 class="text-2xl font-semibold mb-6 flex items-center gap-2">
        <mat-icon>tune</mat-icon>
        {{ 'comparison.title' | translate }}
      </h1>

      <!-- Top bar: Action buttons -->
      <div class="flex flex-wrap items-center gap-3 mb-6">
        <div class="flex gap-2 ml-auto flex-wrap">
          <button
            mat-flat-button
            [disabled]="!weightsTab()?.hasChanges() || !auth.isEdition() || (weightsTab()?.saving() ?? false) || (weightsTab()?.hasValidationErrors() ?? false)"
            (click)="weightsTab()?.saveWeights()"
            [matTooltip]="'comparison.save_tooltip' | translate">
            <mat-icon>save</mat-icon>
            {{ 'comparison.save' | translate }}
          </button>
          <button mat-stroked-button (click)="weightsTab()?.loadWeights()"
            [matTooltip]="'comparison.reset_tooltip' | translate">
            <mat-icon>refresh</mat-icon>
            {{ 'comparison.reset' | translate }}
          </button>
          <button
            mat-stroked-button
            [disabled]="(weightsTab()?.hasChanges() ?? false) || !auth.isEdition() || (weightsTab()?.recalculating() ?? false)"
            (click)="weightsTab()?.recalculateScores()"
            [matTooltip]="'comparison.recalculate_tooltip' | translate">
            @if (weightsTab()?.recalculating()) {
              <mat-spinner diameter="16" />
            } @else {
              <mat-icon>calculate</mat-icon>
            }
            {{ 'comparison.recalculate' | translate }}
          </button>
        </div>
      </div>

      @if (compareFilters.selectedCategory()) {
        <mat-tab-group class="mb-6" [selectedIndex]="0" (selectedIndexChange)="onTabChange($event)">
          <!-- Weights tab -->
          <mat-tab>
            <ng-template mat-tab-label>
              <mat-icon class="mr-2">sliders</mat-icon>
              {{ 'comparison.weights' | translate }}
            </ng-template>
            <app-comparison-weights-tab #weightsTabEl />
          </mat-tab>

          <!-- Snapshots tab -->
          <mat-tab>
            <ng-template mat-tab-label>
              <mat-icon class="mr-2">bookmark</mat-icon>
              {{ 'comparison.snapshots' | translate }}
            </ng-template>
            <app-comparison-snapshots-tab #snapshotsTabEl (restored)="weightsTab()?.loadWeights()" />
          </mat-tab>

          <!-- A/B Compare tab -->
          <mat-tab>
            <ng-template mat-tab-label>
              <mat-icon class="mr-2">compare</mat-icon>
              {{ 'comparison.compare_tab' | translate }}
            </ng-template>
            <app-comparison-ab-tab #abTabEl (weightsApplied)="onWeightsApplied($event)" />
          </mat-tab>
        </mat-tab-group>
      }
    </div>
  `,
})
export class ComparisonComponent {
  auth = inject(AuthService);
  private store = inject(GalleryStore);
  compareFilters = inject(CompareFiltersService);

  weightsTab = viewChild<ComparisonWeightsTabComponent>('weightsTabEl');
  snapshotsTab = viewChild<ComparisonSnapshotsTabComponent>('snapshotsTabEl');
  abTab = viewChild<ComparisonAbTabComponent>('abTabEl');

  constructor() {
    void this.loadCategories();
  }

  async loadCategories(): Promise<void> {
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

  onTabChange(index: number): void {
    if (index === 2 && !this.abTab()?.pairA() && !this.abTab()?.pairLoading()) {
      void this.abTab()?.loadNextPair();
    }
  }

  onWeightsApplied(merged: Record<string, number>): void {
    const tab = this.weightsTab();
    if (tab) tab.weights.set(merged);
  }
}
