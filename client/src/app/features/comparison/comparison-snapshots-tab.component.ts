import { Component, inject, signal, output } from '@angular/core';
import { toObservable, takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { filter, firstValueFrom } from 'rxjs';
import { FormsModule } from '@angular/forms';
import { MatCardModule } from '@angular/material/card';
import { MatButtonModule } from '@angular/material/button';
import { MatIconModule } from '@angular/material/icon';
import { MatFormFieldModule } from '@angular/material/form-field';
import { MatInputModule } from '@angular/material/input';
import { MatSnackBar } from '@angular/material/snack-bar';
import { ApiService } from '../../core/services/api.service';
import { AuthService } from '../../core/services/auth.service';
import { I18nService } from '../../core/services/i18n.service';
import { TranslatePipe } from '../../shared/pipes/translate.pipe';
import { CompareFiltersService } from './compare-filters.service';

interface Snapshot {
  id: number;
  description: string;
  category: string;
  weights: Record<string, number>;
  timestamp: string;
}

@Component({
  selector: 'app-comparison-snapshots-tab',
  standalone: true,
  imports: [
    FormsModule,
    MatCardModule,
    MatButtonModule,
    MatIconModule,
    MatFormFieldModule,
    MatInputModule,
    TranslatePipe,
  ],
  template: `
    <p class="text-sm text-gray-400 mt-4 mb-4">{{ 'comparison.snapshots_description' | translate }}</p>

    @if (scoresStale()) {
      <div class="flex items-center justify-between gap-3 mb-4 p-3 rounded border border-amber-500/40 bg-amber-500/10 text-amber-200">
        <span class="text-sm">{{ 'comparison.scores_stale' | translate }}</span>
        <button mat-flat-button color="primary" [disabled]="recomputing() || !auth.isEdition()" (click)="recalculate()">
          <mat-icon>refresh</mat-icon>
          {{ (recomputing() ? 'comparison.recalculating' : 'comparison.recalculate') | translate }}
        </button>
      </div>
    }

    <div class="grid grid-cols-1 lg:grid-cols-2 gap-6">
      <!-- Save new snapshot -->
      <mat-card>
        <mat-card-header>
          <mat-card-title class="!text-lg">{{ 'comparison.save_snapshot' | translate }}</mat-card-title>
        </mat-card-header>
        <mat-card-content class="!pt-4">
          <mat-form-field class="w-full">
            <mat-label>{{ 'comparison.snapshot_name' | translate }}</mat-label>
            <input matInput [ngModel]="snapshotName()" (ngModelChange)="snapshotName.set($event)" (keyup.enter)="saveSnapshot()" />
          </mat-form-field>
          <button mat-flat-button [disabled]="!snapshotName().trim() || !auth.isEdition()" (click)="saveSnapshot()">
            <mat-icon>save</mat-icon>
            {{ 'comparison.save' | translate }}
          </button>
        </mat-card-content>
      </mat-card>

      <!-- Snapshot list -->
      <mat-card>
        <mat-card-header>
          <mat-card-title class="!text-lg">{{ 'comparison.saved_snapshots' | translate }}</mat-card-title>
        </mat-card-header>
        <mat-card-content class="!pt-4">
          @if (snapshots().length > 0) {
            <div class="flex flex-col gap-2 max-h-96 overflow-y-auto" (scroll)="onSnapshotsScroll($event)">
              @for (snap of snapshots(); track snap.id) {
                <div class="flex items-center justify-between gap-2 p-2 rounded bg-neutral-800/50">
                  <div class="min-w-0">
                    <div class="text-sm truncate">{{ snap.description }}</div>
                    <div class="text-xs text-gray-400">{{ snap.category }} &mdash; {{ snap.timestamp }}</div>
                  </div>
                  <div class="flex gap-1 shrink-0">
                    <button mat-icon-button [disabled]="!auth.isEdition()" (click)="restoreSnapshot(snap.id)"
                      [attr.aria-label]="'comparison.restore' | translate">
                      <mat-icon>restore</mat-icon>
                    </button>
                  </div>
                </div>
              }
              @if (loadingSnapshots()) {
                <p class="text-gray-500 text-xs text-center py-2">{{ 'common.loading' | translate }}</p>
              }
            </div>
          } @else {
            <p class="text-gray-500 text-sm">{{ 'comparison.no_snapshots' | translate }}</p>
          }
        </mat-card-content>
      </mat-card>
    </div>
  `,
})
export class ComparisonSnapshotsTabComponent {
  private api = inject(ApiService);
  private i18n = inject(I18nService);
  private snackBar = inject(MatSnackBar);
  readonly auth = inject(AuthService);
  private compareFilters = inject(CompareFiltersService);

  snapshots = signal<Snapshot[]>([]);
  snapshotName = signal('');
  scoresStale = signal<string | null>(null);
  recomputing = signal(false);
  hasMoreSnapshots = signal(true);
  loadingSnapshots = signal(false);
  private readonly SNAPSHOT_PAGE = 20;

  /** Emitted after a snapshot is successfully restored — parent reloads weights */
  readonly restored = output<void>();

  constructor() {
    toObservable(this.compareFilters.selectedCategory).pipe(
      filter(Boolean),
      takeUntilDestroyed(),
    ).subscribe(() => void this.loadSnapshots());
  }

  async loadSnapshots(): Promise<void> {
    this.snapshots.set([]);
    this.hasMoreSnapshots.set(true);
    await this.loadMoreSnapshots();
  }

  async loadMoreSnapshots(): Promise<void> {
    if (this.loadingSnapshots() || !this.hasMoreSnapshots()) return;
    this.loadingSnapshots.set(true);
    const cat = this.compareFilters.selectedCategory();
    const params: Record<string, string | number> = { offset: this.snapshots().length, limit: this.SNAPSHOT_PAGE };
    if (cat) params['category'] = cat;
    try {
      const res = await firstValueFrom(
        this.api.get<{ snapshots: Snapshot[]; has_more: boolean }>('/config/weight_snapshots', params),
      );
      this.snapshots.update(cur => [...cur, ...(res.snapshots ?? [])]);
      this.hasMoreSnapshots.set(!!res.has_more);
    } catch {
      this.hasMoreSnapshots.set(false);
      this.snackBar.open(this.i18n.t('comparison.error_loading_snapshots'), '', { duration: 4000 });
    } finally {
      this.loadingSnapshots.set(false);
    }
  }

  onSnapshotsScroll(event: Event): void {
    const el = event.target as HTMLElement;
    if (el.scrollTop + el.clientHeight >= el.scrollHeight - 48) {
      void this.loadMoreSnapshots();
    }
  }

  async saveSnapshot(): Promise<void> {
    const name = this.snapshotName().trim();
    if (!name) return;
    try {
      await firstValueFrom(this.api.post('/config/save_snapshot', {
        category: this.compareFilters.selectedCategory(),
        description: name,
      }));
      this.snapshotName.set('');
      this.snackBar.open(this.i18n.t('comparison.snapshot_saved'), '', { duration: 3000 });
      await this.loadSnapshots();
    } catch {
      this.snackBar.open(this.i18n.t('comparison.error_saving_snapshot'), '', { duration: 4000 });
    }
  }

  async restoreSnapshot(id: number): Promise<void> {
    try {
      const res = await firstValueFrom(
        this.api.post<{ category: string }>('/config/restore_weights', { snapshot_id: id }),
      );
      this.snackBar.open(this.i18n.t('comparison.snapshot_restored'), '', { duration: 3000 });
      this.scoresStale.set(res?.category ?? this.compareFilters.selectedCategory());
      this.restored.emit();
      await this.loadSnapshots();
    } catch {
      this.snackBar.open(this.i18n.t('comparison.error_restoring_snapshot'), '', { duration: 4000 });
    }
  }

  async recalculate(): Promise<void> {
    const category = this.scoresStale();
    if (!category) return;
    this.recomputing.set(true);
    try {
      await firstValueFrom(this.api.post('/stats/categories/recompute', { category }));
      this.scoresStale.set(null);
      this.snackBar.open(this.i18n.t('comparison.scores_recalculated'), '', { duration: 3000 });
    } catch {
      this.snackBar.open(this.i18n.t('comparison.error_recalculating'), '', { duration: 4000 });
    } finally {
      this.recomputing.set(false);
    }
  }

}
