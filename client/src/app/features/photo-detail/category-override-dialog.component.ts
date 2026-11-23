import { ChangeDetectionStrategy, Component, OnInit, inject, signal } from '@angular/core';
import { MAT_DIALOG_DATA, MatDialogModule, MatDialogRef } from '@angular/material/dialog';
import { MatButtonModule } from '@angular/material/button';
import { MatFormFieldModule } from '@angular/material/form-field';
import { MatSelectModule } from '@angular/material/select';
import { MatProgressSpinnerModule } from '@angular/material/progress-spinner';
import { MatSnackBar } from '@angular/material/snack-bar';
import { firstValueFrom } from 'rxjs';
import { ApiService } from '../../core/services/api.service';
import { I18nService } from '../../core/services/i18n.service';
import { TranslatePipe } from '../../shared/pipes/translate.pipe';
import { CategoryLabelPipe } from '../../shared/pipes/category-label.pipe';
import { I18N, i18nKeys } from '../../core/i18n/keys';

export interface CategoryOverrideDialogData {
  path: string;
  currentCategory: string | null;
}

export interface CategoryOverrideResult {
  category: string;
  aggregate: number;
}

interface CategoryOption {
  name: string;
}

/**
 * Edition-only dialog that sets the sticky per-photo category override — the
 * escape hatch for the single stubborn frame the scoring-context filters
 * still can't reach. Survives the next recompute (unlike a plain filter match).
 */
@Component({
  selector: 'app-category-override-dialog',
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [MatDialogModule, MatButtonModule, MatFormFieldModule, MatSelectModule, MatProgressSpinnerModule, TranslatePipe, CategoryLabelPipe],
  template: `
    <h2 mat-dialog-title>{{ I18N.photo.category_override.dialog_title | translate }}</h2>
    <mat-dialog-content class="!pt-2 min-w-[16rem]">
      @if (loading()) {
        <div class="flex justify-center py-4">
          <mat-spinner diameter="28" [attr.aria-label]="I18N.ui.labels.loading | translate" />
        </div>
      } @else if (loadFailed()) {
        <p role="alert" class="text-sm text-[var(--mat-sys-on-error-container)] bg-[var(--mat-sys-error-container)] rounded-md p-3">
          {{ I18N.errors.server_error | translate }}
          <button type="button" class="underline" (click)="loadCategories()">{{ I18N.gallery.load_error.retry | translate }}</button>
        </p>
      } @else {
        <mat-form-field class="w-full">
          <mat-label>{{ I18N.photo.category_override.label | translate }}</mat-label>
          <mat-select [value]="selectedCategory()" (selectionChange)="selectedCategory.set($event.value)">
            @for (name of categories(); track name) {
              <mat-option [value]="name">{{ name | categoryLabel }}</mat-option>
            }
          </mat-select>
        </mat-form-field>
      }
    </mat-dialog-content>
    <mat-dialog-actions align="end">
      <button mat-button mat-dialog-close>{{ I18N.ui.buttons.cancel | translate }}</button>
      <button mat-flat-button [disabled]="!selectedCategory() || saving() || loadFailed()" (click)="save()">
        {{ saving() ? (I18N.ui.buttons.saving | translate) : (I18N.ui.buttons.save | translate) }}
      </button>
    </mat-dialog-actions>
  `,
})
export class CategoryOverrideDialogComponent implements OnInit {
  protected readonly I18N = i18nKeys();
  private readonly api = inject(ApiService);
  private readonly i18n = inject(I18nService);
  private readonly snackBar = inject(MatSnackBar);
  private readonly dialogRef = inject(MatDialogRef<CategoryOverrideDialogComponent>);
  protected readonly data = inject<CategoryOverrideDialogData>(MAT_DIALOG_DATA);

  protected readonly loading = signal(true);
  protected readonly loadFailed = signal(false);
  protected readonly saving = signal(false);
  protected readonly categories = signal<string[]>([]);
  protected readonly selectedCategory = signal(this.data.currentCategory ?? '');

  async ngOnInit(): Promise<void> {
    await this.loadCategories();
  }

  protected async loadCategories(): Promise<void> {
    this.loading.set(true);
    this.loadFailed.set(false);
    try {
      const res = await firstValueFrom(this.api.get<{ categories: CategoryOption[] }>('/config/category_priorities'));
      const names = res.categories.map(c => c.name);
      this.categories.set(names);
      if (!this.selectedCategory() && names.length) {
        this.selectedCategory.set(names[0]);
      }
    } catch {
      // The snackbar alone leaves the dialog permanently unusable once the
      // spinner ends: an empty dropdown with a disabled save and no way back
      // except cancelling. A visible in-dialog retry re-arms the load.
      this.loadFailed.set(true);
      this.snackBar.open(this.i18n.t(I18N.notifications.connection_error), '', { duration: 3000 });
    } finally {
      this.loading.set(false);
    }
  }

  protected async save(): Promise<void> {
    const category = this.selectedCategory();
    if (!category || this.saving()) return;
    this.saving.set(true);
    try {
      const res = await firstValueFrom(
        this.api.post<{ new_category: string; aggregate: number }>('/comparison/override_category', { path: this.data.path, category }),
      );
      this.snackBar.open(this.i18n.t(I18N.photo.category_override.success, { category: res.new_category }), '', { duration: 3000 });
      this.dialogRef.close({ category: res.new_category, aggregate: res.aggregate });
    } catch {
      this.snackBar.open(this.i18n.t(I18N.errors.action_failed), '', { duration: 3000 });
      this.saving.set(false);
    }
  }
}
