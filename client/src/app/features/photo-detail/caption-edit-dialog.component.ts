import { Component, inject, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { MatDialogModule, MatDialogRef, MAT_DIALOG_DATA } from '@angular/material/dialog';
import { MatButtonModule } from '@angular/material/button';
import { MatIconModule } from '@angular/material/icon';
import { MatFormFieldModule } from '@angular/material/form-field';
import { MatInputModule } from '@angular/material/input';
import { firstValueFrom } from 'rxjs';
import { ApiService } from '../../core/services/api.service';
import { TranslatePipe } from '../../shared/pipes/translate.pipe';
import { I18N } from '../../core/i18n/keys';

export interface CaptionEditDialogData {
  path: string;
  filename: string;
  caption: string;
}

@Component({
  selector: 'app-caption-edit-dialog',
  standalone: true,
  imports: [FormsModule, MatDialogModule, MatButtonModule, MatIconModule, MatFormFieldModule, MatInputModule, TranslatePipe],
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
    </mat-dialog-content>
    <mat-dialog-actions align="end">
      <button mat-button mat-dialog-close>{{ I18N.ui.buttons.cancel | translate }}</button>
      <button mat-flat-button (click)="save()" [disabled]="saving()">{{ I18N.ui.buttons.save | translate }}</button>
    </mat-dialog-actions>
  `,
})
export class CaptionEditDialogComponent {
  protected readonly I18N = I18N;
  private readonly api = inject(ApiService);
  private readonly dialogRef = inject(MatDialogRef<CaptionEditDialogComponent>);
  readonly data: CaptionEditDialogData = inject(MAT_DIALOG_DATA);

  captionText = this.data.caption;
  readonly saving = signal(false);

  async save(): Promise<void> {
    this.saving.set(true);
    try {
      await firstValueFrom(this.api.put('/caption', { path: this.data.path, caption: this.captionText }));
      this.dialogRef.close(this.captionText);
    } catch {
      // Error handling — dialog stays open
    } finally {
      this.saving.set(false);
    }
  }
}
