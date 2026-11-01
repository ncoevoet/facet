import { ChangeDetectionStrategy, Component, inject } from '@angular/core';
import { MAT_DIALOG_DATA, MatDialogModule } from '@angular/material/dialog';
import { MatButtonModule } from '@angular/material/button';
import { MatIconModule } from '@angular/material/icon';
import { I18N } from '../../core/i18n/keys';
import { TranslatePipe } from '../../shared/pipes/translate.pipe';
import { PhotoAnalysisComponent } from './photo-analysis.component';

/** Other collection surfaces keep their explicit dialog; the photo page embeds the same evidence. */
@Component({
  selector: 'app-photo-critique-dialog',
  imports: [MatDialogModule, MatButtonModule, MatIconModule, TranslatePipe, PhotoAnalysisComponent],
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    <h2 mat-dialog-title class="!flex items-center gap-2">
      <mat-icon aria-hidden="true">analytics</mat-icon><span class="flex-1">{{ I18N.critique.title | translate }}</span>
      <button mat-icon-button mat-dialog-close [attr.aria-label]="I18N.critique.close | translate"><mat-icon>close</mat-icon></button>
    </h2>
    <mat-dialog-content class="!max-h-[70vh]"><app-photo-analysis [photoPath]="data.photoPath" [vlmAvailable]="data.vlmAvailable" /></mat-dialog-content>
  `,
})
export class PhotoCritiqueDialogComponent {
  protected readonly I18N = I18N;
  protected readonly data = inject<{ photoPath: string; vlmAvailable: boolean }>(MAT_DIALOG_DATA);
}
