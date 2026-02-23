import { Component, inject } from '@angular/core';
import { MatButtonModule } from '@angular/material/button';
import { MatDialogModule, MAT_DIALOG_DATA, MatDialogRef } from '@angular/material/dialog';
import { TranslatePipe } from '../../pipes/translate.pipe';

@Component({
  selector: 'app-confirm-dialog',
  standalone: true,
  imports: [MatButtonModule, MatDialogModule, TranslatePipe],
  template: `
    <h2 mat-dialog-title>{{ data.title }}</h2>
    <mat-dialog-content>
      <p>{{ data.message }}</p>
    </mat-dialog-content>
    <mat-dialog-actions align="end">
      <button mat-button (click)="dialogRef.close(false)">
        {{ data.cancelLabel ?? ('dialog.cancel' | translate) }}
      </button>
      <button mat-flat-button color="warn" (click)="dialogRef.close(true)">
        {{ data.confirmLabel ?? ('dialog.confirm' | translate) }}
      </button>
    </mat-dialog-actions>
  `,
})
export class ConfirmDialogComponent {
  data: { title: string; message: string; cancelLabel?: string; confirmLabel?: string } =
    inject(MAT_DIALOG_DATA);
  dialogRef = inject(MatDialogRef<ConfirmDialogComponent>);
}
