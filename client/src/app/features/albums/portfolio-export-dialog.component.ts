import { ChangeDetectionStrategy, Component, inject, signal } from '@angular/core';
import { MAT_DIALOG_DATA, MatDialogRef, MatDialogModule } from '@angular/material/dialog';
import { MatButtonModule } from '@angular/material/button';
import { MatCheckboxModule } from '@angular/material/checkbox';
import { MatProgressSpinnerModule } from '@angular/material/progress-spinner';
import { MatSnackBar } from '@angular/material/snack-bar';
import { firstValueFrom } from 'rxjs';
import { ApiService } from '../../core/services/api.service';
import { I18nService } from '../../core/services/i18n.service';
import { TranslatePipe } from '../../shared/pipes/translate.pipe';
import { I18N } from '../../core/i18n/keys';

interface PortfolioExportResponse {
  exported: number;
  from_original: number;
  from_thumbnail: number;
  output_dir: string;
}

export interface PortfolioExportDialogData {
  albumId: number;
  albumName: string;
}

/**
 * Edition-only "Export portfolio" dialog: renders an album into a self-contained
 * static HTML gallery inside a target folder on the server host.
 */
@Component({
  selector: 'app-portfolio-export-dialog',
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [MatDialogModule, MatButtonModule, MatCheckboxModule,
            MatProgressSpinnerModule, TranslatePipe],
  template: `
    <h2 mat-dialog-title>{{ I18N.portfolio.title | translate }}</h2>
    <mat-dialog-content class="!pt-2 min-w-[22rem] max-w-[32rem]">
      <p class="text-sm opacity-70 mb-3">{{ I18N.portfolio.description | translate }}</p>

      <label for="pfTitle" class="block text-xs opacity-60 mb-1">{{ I18N.portfolio.gallery_title | translate }}</label>
      <input id="pfTitle" type="text" [value]="title()" (input)="onTitleInput($event)"
             class="w-full text-sm rounded border border-[var(--mat-sys-outline-variant)] bg-transparent px-2 py-1.5 mb-3" />

      <label for="pfTarget" class="block text-xs opacity-60 mb-1">{{ I18N.portfolio.target_dir | translate }}</label>
      <input id="pfTarget" type="text" [value]="targetDir()" (input)="onTargetInput($event)"
             class="w-full text-sm font-mono rounded border border-[var(--mat-sys-outline-variant)] bg-transparent px-2 py-1.5 mb-3"
             placeholder="/path/to/folder" />

      <mat-checkbox [checked]="includeCaptions()" (change)="includeCaptions.set($event.checked)"
                    class="text-sm">
        {{ I18N.portfolio.include_captions | translate }}
      </mat-checkbox>
    </mat-dialog-content>
    <mat-dialog-actions align="end">
      <button mat-button mat-dialog-close>{{ I18N.portfolio.cancel | translate }}</button>
      <button mat-flat-button color="primary" [disabled]="busy() || !targetDir()"
              (click)="exportPortfolio()">
        @if (busy()) { <mat-spinner diameter="16" class="!inline-block !align-middle !mr-1" /> }
        {{ I18N.portfolio.export | translate }}
      </button>
    </mat-dialog-actions>
  `,
})
export class PortfolioExportDialogComponent {
  protected readonly I18N = I18N;
  private readonly api = inject(ApiService);
  private readonly snackBar = inject(MatSnackBar);
  private readonly i18n = inject(I18nService);
  private readonly dialogRef = inject(MatDialogRef<PortfolioExportDialogComponent>);
  private readonly data = inject<PortfolioExportDialogData>(MAT_DIALOG_DATA);

  protected readonly title = signal(this.data.albumName ?? '');
  protected readonly targetDir = signal('');
  protected readonly includeCaptions = signal(true);
  protected readonly busy = signal(false);

  protected onTitleInput(event: Event): void {
    this.title.set((event.target as HTMLInputElement).value);
  }

  protected onTargetInput(event: Event): void {
    this.targetDir.set((event.target as HTMLInputElement).value);
  }

  async exportPortfolio(): Promise<void> {
    this.busy.set(true);
    try {
      const res = await firstValueFrom(this.api.post<PortfolioExportResponse>(
        `/albums/${this.data.albumId}/export-portfolio`,
        { target_dir: this.targetDir(), title: this.title(), include_captions: this.includeCaptions() },
      ));
      this.snackBar.open(this.i18n.t(I18N.portfolio.done, { count: res.exported }), '', { duration: 3000 });
      this.dialogRef.close(true);
    } catch {
      this.snackBar.open(this.i18n.t(I18N.portfolio.error), '', { duration: 3000 });
    } finally {
      this.busy.set(false);
    }
  }
}
