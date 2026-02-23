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
            <div class="flex flex-col gap-2">
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

  /** Emitted after a snapshot is successfully restored — parent reloads weights */
  readonly restored = output<void>();

  constructor() {
    toObservable(this.compareFilters.selectedCategory).pipe(
      filter(Boolean),
      takeUntilDestroyed(),
    ).subscribe(() => void this.loadSnapshots());
  }

  async loadSnapshots(): Promise<void> {
    const cat = this.compareFilters.selectedCategory();
    try {
      const res = await firstValueFrom(
        this.api.get<{ snapshots: Snapshot[] }>('/config/weight_snapshots', cat ? { category: cat } : {}),
      );
      this.snapshots.set(res.snapshots ?? []);
    } catch {
      this.snackBar.open(this.i18n.t('comparison.error_loading_snapshots'), '', { duration: 4000 });
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
      await firstValueFrom(this.api.post('/config/restore_weights', { snapshot_id: id }));
      this.snackBar.open(this.i18n.t('comparison.snapshot_restored'), '', { duration: 3000 });
      this.restored.emit();
    } catch {
      this.snackBar.open(this.i18n.t('comparison.error_restoring_snapshot'), '', { duration: 4000 });
    }
  }

}
