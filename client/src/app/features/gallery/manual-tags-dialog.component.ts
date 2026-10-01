import { Component, inject, signal } from '@angular/core';
import { MatDialogModule, MatDialogRef, MAT_DIALOG_DATA } from '@angular/material/dialog';
import { MatButtonModule } from '@angular/material/button';
import { MatIconModule } from '@angular/material/icon';
import { MatFormFieldModule } from '@angular/material/form-field';
import { MatInputModule } from '@angular/material/input';
import { firstValueFrom } from 'rxjs';
import { ApiService } from '../../core/services/api.service';
import { TranslatePipe } from '../../shared/pipes/translate.pipe';
import { I18N_KEYS } from '../../core/i18n/keys';
import { chunkPhotoPaths } from './gallery.store';

/** The set the tag is applied to: named paths, or the gallery view itself. */
export interface ManualTagsDialogData {
  paths: string[];
  /** Whole-view selection: the filter travels instead of the path list. */
  filters?: Record<string, unknown> | null;
  exclude?: string[];
  /** How many photos the selection stands for (larger than `paths.length` under view scope). */
  count: number;
}

type ManualTagAction = 'add' | 'delete';

/** Adds or removes one manual tag across the gallery selection. Owns its request. */
@Component({
  selector: 'app-manual-tags-dialog',
  standalone: true,
  imports: [MatDialogModule, MatButtonModule, MatIconModule, MatFormFieldModule, MatInputModule, TranslatePipe],
  template: `
    <h2 mat-dialog-title class="flex items-center gap-2">
      <mat-icon aria-hidden="true">sell</mat-icon>
      <span>{{ I18N.manual_tags.title | translate }}</span>
    </h2>
    <mat-dialog-content>
      <p class="text-sm opacity-70 mb-3">{{ I18N.gallery.selection.count | translate:{ count: data.count } }}</p>
      <mat-form-field class="w-full" subscriptSizing="dynamic">
        <mat-label>{{ I18N.manual_tags.tag_label | translate }}</mat-label>
        <input matInput maxlength="64" [value]="tag()" (input)="onInput($event)" (keydown.enter)="!saving() && apply('add')" />
        <mat-hint>{{ I18N.manual_tags.hint | translate }}</mat-hint>
      </mat-form-field>
      @if (failed()) {
        <p class="text-sm text-red-400 mt-3" role="alert">{{ I18N.manual_tags.error | translate }}</p>
      }
    </mat-dialog-content>
    <mat-dialog-actions align="end">
      <button mat-button (click)="cancel()">{{ I18N.ui.buttons.cancel | translate }}</button>
      <button mat-button (click)="apply('delete')" [disabled]="saving() || !tag().trim()">{{ I18N.manual_tags.remove_action | translate }}</button>
      <button mat-flat-button (click)="apply('add')" [disabled]="saving() || !tag().trim()">{{ I18N.manual_tags.add_action | translate }}</button>
    </mat-dialog-actions>
  `,
})
export class ManualTagsDialogComponent {
  protected readonly I18N = I18N_KEYS;
  private readonly api = inject(ApiService);
  private readonly dialogRef = inject(MatDialogRef<ManualTagsDialogComponent>);
  readonly data: ManualTagsDialogData = inject(MAT_DIALOG_DATA);

  readonly tag = signal('');
  readonly saving = signal(false);
  readonly failed = signal(false);
  /** Photos already written by chunks that succeeded before a later chunk failed. */
  private committed = 0;

  protected onInput(event: Event): void {
    this.tag.set((event.target as HTMLInputElement).value);
  }

  /** One request for a whole-view filter; path lists go in chunks the server's cap accepts. */
  private bodies(): Record<string, unknown>[] {
    const filters = this.data.filters ?? null;
    if (filters) return [{ filters, exclude: this.data.exclude ?? [] }];
    return chunkPhotoPaths(this.data.paths).map(chunk => ({ photo_paths: chunk }));
  }

  /**
   * Closes with the count committed by a partially failed save, so the gallery
   * (which reloads on any truthy result) does not keep showing stale rows.
   */
  cancel(): void {
    this.dialogRef.close(this.committed || undefined);
  }

  async apply(action: ManualTagAction): Promise<void> {
    const tag = this.tag().trim();
    if (!tag || this.saving()) return;
    this.saving.set(true);
    this.failed.set(false);
    let total = 0;
    try {
      for (const body of this.bodies()) {
        const res = await firstValueFrom(
          this.api.post<{ count: number }>('/photos/batch_manual_tags', { ...body, tag, action }));
        total += res.count;
        this.committed += res.count;
      }
      this.dialogRef.close(total);
    } catch {
      this.failed.set(true);
      // Escape and backdrop close with undefined: once a chunk landed, only
      // cancel() may close, so the gallery still reloads.
      if (this.committed) this.dialogRef.disableClose = true;
    } finally {
      this.saving.set(false);
    }
  }
}
