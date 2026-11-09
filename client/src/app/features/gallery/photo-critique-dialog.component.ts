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
    <!-- The app's dialog header; before:!content-none drops Material's baseline strut, which a
         flex title would otherwise lay out as an item and offset the icon by one gap. -->
    <h2 mat-dialog-title class="!flex !items-center !gap-3 !text-base !font-semibold !m-0 !px-6 !pt-5 !pb-4 before:!content-none">
      <span class="w-9 h-9 rounded-lg bg-[var(--mat-sys-primary-container)] flex items-center justify-center shrink-0">
        <mat-icon aria-hidden="true" class="!text-xl !leading-none !w-5 !h-5 text-[var(--mat-sys-on-primary-container)]">analytics</mat-icon>
      </span>
      <span class="min-w-0 flex-1">{{ I18N.critique.title | translate }}</span>
      <button mat-icon-button mat-dialog-close class="-mr-1.5 shrink-0" [attr.aria-label]="I18N.critique.close | translate"><mat-icon>close</mat-icon></button>
    </h2>
    <mat-dialog-content class="!max-h-[70vh]"><app-photo-analysis [photoPath]="data.photoPath" [vlmAvailable]="data.vlmAvailable" /></mat-dialog-content>
  `,
})
export class PhotoCritiqueDialogComponent {
  protected readonly I18N = I18N;
  protected readonly data = inject<{ photoPath: string; vlmAvailable: boolean }>(MAT_DIALOG_DATA);
}
