import { Component, inject, signal, viewChild, ElementRef, afterNextRender, ChangeDetectionStrategy, DestroyRef, Injector } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { MatDialogModule, MatDialogRef, MAT_DIALOG_DATA } from '@angular/material/dialog';
import { MatButtonModule } from '@angular/material/button';
import { MatIconModule } from '@angular/material/icon';
import { MatFormFieldModule } from '@angular/material/form-field';
import { MatInputModule } from '@angular/material/input';
import { firstValueFrom } from 'rxjs';
import { ApiService } from '../../core/services/api.service';
import { GalleryStore } from '../gallery/gallery.store';
import { TranslatePipe } from '../../shared/pipes/translate.pipe';
import { i18nKeys } from '../../core/i18n/keys';

export interface CaptionEditDialogData {
  path: string;
  filename: string;
  caption: string;
}

@Component({
  selector: 'app-caption-edit-dialog',
  standalone: true,
  imports: [FormsModule, MatDialogModule, MatButtonModule, MatIconModule, MatFormFieldModule, MatInputModule, TranslatePipe],
  changeDetection: ChangeDetectionStrategy.Eager,
  template: `
    <h2 mat-dialog-title class="flex items-center gap-2">
      <mat-icon>description</mat-icon>
      <span class="truncate">{{ data.filename }}</span>
    </h2>
    <mat-dialog-content>
      <mat-form-field class="w-full" subscriptSizing="dynamic">
        <mat-label>{{ I18N.photo_detail.caption | translate }}</mat-label>
        <textarea matInput [(ngModel)]="captionText" rows="4"></textarea>
      </mat-form-field>
      @if (saveFailed()) {
        <p #saveError role="alert" tabindex="-1" class="rounded-md bg-[var(--mat-sys-error-container)] p-3 text-[var(--mat-sys-on-error-container)]">{{ I18N.errors.action_failed | translate }}</p>
      }
    </mat-dialog-content>
    <mat-dialog-actions align="end">
      <button mat-button [mat-dialog-close]="undefined">{{ I18N.ui.buttons.cancel | translate }}</button>
      <button #saveButton mat-flat-button (click)="save()" [disabled]="saving()">{{ I18N.ui.buttons.save | translate }}</button>
    </mat-dialog-actions>
  `,
})
export class CaptionEditDialogComponent {
  protected readonly I18N = i18nKeys();
  private readonly api = inject(ApiService);
  private readonly destroyRef = inject(DestroyRef);
  private readonly injector = inject(Injector);
  private readonly store = inject(GalleryStore);
  private readonly dialogRef = inject(MatDialogRef<CaptionEditDialogComponent>);
  readonly data: CaptionEditDialogData = inject(MAT_DIALOG_DATA);

  captionText = this.data.caption;
  readonly saving = signal(false);
  readonly saveFailed = signal(false);
  private readonly saveButton = viewChild<ElementRef<HTMLButtonElement>>('saveButton');

  async save(): Promise<void> {
    if (this.saving()) return;
    const caption = this.captionText;
    this.saving.set(true);
    this.saveFailed.set(false);
    try {
      await firstValueFrom(this.api.put('/caption', { path: this.data.path, caption }));
      // Back closes this dialog before the save lands, so the caller would never hear of it.
      this.store.patchPhoto(this.data.path, { caption: caption || null, caption_translated: undefined });
      if (!this.destroyRef.destroyed) this.dialogRef.close(caption);
    } catch {
      // The dialog stays open: without feedback the user believes the caption saved.
      this.saveFailed.set(true);
      // Back may already have closed the dialog: a destroyed injector throws NG0911.
      if (!this.destroyRef.destroyed) {
        afterNextRender(() => this.saveButton()?.nativeElement.focus(), { injector: this.injector });
      }
    } finally {
      this.saving.set(false);
    }
  }
}
