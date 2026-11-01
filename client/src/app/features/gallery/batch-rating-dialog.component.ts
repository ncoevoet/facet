import { ChangeDetectionStrategy, Component, computed, inject, signal } from '@angular/core';
import { MAT_DIALOG_DATA, MatDialogModule, MatDialogRef } from '@angular/material/dialog';
import { MatButtonModule } from '@angular/material/button';
import { I18N } from '../../core/i18n/keys';
import { TranslatePipe } from '../../shared/pipes/translate.pipe';

export interface BatchRatingPreview {
  paths: string[];
  rating: number;
  observed: { rating: number; count: number }[];
  loaded: number;
  wholeView: boolean;
}

@Component({
  selector: 'app-batch-rating-dialog',
  imports: [MatDialogModule, MatButtonModule, TranslatePipe],
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    <h2 mat-dialog-title>{{ I18N.gallery.rating_preview.title | translate }}</h2>
    <mat-dialog-content>
      <p class="font-medium">{{ I18N.gallery.rating_preview.target | translate:{ count: data.paths.length } }}</p>
      <p class="text-sm">{{ (data.wholeView ? I18N.gallery.rating_preview.whole_scope : I18N.gallery.rating_preview.scope) | translate }}</p>
      <details class="my-3">
        <summary class="cursor-pointer py-1">{{ I18N.gallery.rating_preview.observed | translate:{ loaded: data.loaded, total: data.paths.length } }}</summary>
        <ul class="my-2 flex list-none flex-wrap gap-2 p-0">
          @for (item of data.observed; track item.rating) { <li class="rounded bg-[var(--mat-sys-surface-container)] px-2 py-1">{{ item.rating }} ★ · {{ item.count }}/{{ data.loaded }}</li> }
        </ul>
        <p class="text-xs">{{ I18N.gallery.rating_preview.unknown | translate }}</p>
      </details>
      <label class="flex items-center gap-3">{{ I18N.gallery.rating_preview.operation | translate }}
        <select data-rating-value class="min-h-11 rounded border bg-[var(--mat-sys-surface-container)] px-3" [value]="rating()" (change)="choose($event)">
          <option value="0">{{ I18N.gallery.rating_preview.clear | translate }}</option>
          @for (value of [1,2,3,4,5]; track value) { <option [value]="value">{{ value }} ★</option> }
        </select>
      </label>
      <p data-rating-plan class="my-3 rounded border border-[var(--mat-sys-outline-variant)] p-3">{{ (rating() === 0 ? I18N.gallery.rating_preview.clear_plan : I18N.gallery.rating_preview.set_plan) | translate:{ count: data.paths.length, rating: rating() } }}</p>
      <p class="text-xs">{{ I18N.gallery.rating_preview.boundary | translate }}</p>
    </mat-dialog-content>
    <mat-dialog-actions align="end">
      <button mat-button mat-dialog-close>{{ I18N.ui.buttons.cancel | translate }}</button>
      <button mat-flat-button data-apply-rating [disabled]="!valid()" (click)="apply()">{{ I18N.ui.buttons.apply | translate }}</button>
    </mat-dialog-actions>
  `,
})
export class BatchRatingDialogComponent {
  protected readonly I18N = I18N;
  readonly data = structuredClone(inject<BatchRatingPreview>(MAT_DIALOG_DATA));
  private readonly ref = inject(MatDialogRef<BatchRatingDialogComponent, number>);
  readonly rating = signal(this.data.rating);
  protected readonly valid = computed(() => Number.isInteger(this.rating()) && this.rating() >= 0 && this.rating() <= 5);
  protected choose(event: Event): void { this.rating.set(Number((event.target as HTMLSelectElement).value)); }
  protected apply(): void { if (this.valid()) this.ref.close(this.rating()); }
}
