import { Component, inject, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { MAT_DIALOG_DATA, MatDialogModule, MatDialogRef } from '@angular/material/dialog';
import { MatFormFieldModule } from '@angular/material/form-field';
import { MatInputModule } from '@angular/material/input';
import { MatButtonModule } from '@angular/material/button';
import { MatCheckboxModule } from '@angular/material/checkbox';
import { MatRadioModule } from '@angular/material/radio';
import { MatIconModule } from '@angular/material/icon';
import { MatProgressSpinnerModule } from '@angular/material/progress-spinner';
import { MatSnackBar } from '@angular/material/snack-bar';
import { firstValueFrom } from 'rxjs';
import { AlbumExportMode, ExportService } from '../../core/services/export.service';
import { I18nService } from '../../core/services/i18n.service';
import { TranslatePipe } from '../../shared/pipes/translate.pipe';

export interface ExportEditorDialogData {
  /** Explicit selected photo paths (gallery selection). */
  paths?: string[];
  /** Album id when exporting a whole album ("basket"). */
  albumId?: number;
}

@Component({
  selector: 'app-export-editor-dialog',
  standalone: true,
  imports: [
    FormsModule, MatDialogModule, MatFormFieldModule, MatInputModule,
    MatButtonModule, MatCheckboxModule, MatRadioModule, MatIconModule,
    MatProgressSpinnerModule, TranslatePipe,
  ],
  template: `
    <h2 mat-dialog-title>{{ 'export.title' | translate }}</h2>
    <mat-dialog-content class="flex flex-col gap-3">
      <p class="text-sm opacity-80">{{ 'export.description' | translate }}</p>

      <mat-radio-group [(ngModel)]="mode" class="flex flex-col gap-2">
        <mat-radio-button value="sidecars">{{ 'export.mode_sidecars' | translate }}</mat-radio-button>
        @if (data.albumId) {
          <mat-radio-button value="copy">{{ 'export.mode_copy' | translate }}</mat-radio-button>
          <mat-radio-button value="symlink">{{ 'export.mode_symlink' | translate }}</mat-radio-button>
        }
      </mat-radio-group>

      @if (mode === 'sidecars') {
        <mat-checkbox [(ngModel)]="overwrite">{{ 'export.overwrite' | translate }}</mat-checkbox>
        <p class="text-xs opacity-60">{{ 'export.overwrite_hint' | translate }}</p>
      } @else {
        <mat-form-field class="w-full">
          <mat-label>{{ 'export.target_dir' | translate }}</mat-label>
          <input matInput [(ngModel)]="targetDir" />
        </mat-form-field>
      }
    </mat-dialog-content>
    <mat-dialog-actions align="end">
      <button mat-button mat-dialog-close>{{ 'ui.buttons.cancel' | translate }}</button>
      <button mat-flat-button [disabled]="!canRun() || running()" (click)="run()">
        @if (running()) { <mat-spinner diameter="18" class="!inline-block !align-baseline"></mat-spinner> }
        {{ running() ? ('export.running' | translate) : ('export.run' | translate) }}
      </button>
    </mat-dialog-actions>
  `,
})
export class ExportEditorDialogComponent {
  protected readonly data = inject<ExportEditorDialogData>(MAT_DIALOG_DATA);
  private readonly exportService = inject(ExportService);
  private readonly dialogRef = inject(MatDialogRef<ExportEditorDialogComponent>);
  private readonly snackBar = inject(MatSnackBar);
  private readonly i18n = inject(I18nService);

  mode: AlbumExportMode = 'sidecars';
  overwrite = false;
  targetDir = '';
  readonly running = signal(false);

  canRun(): boolean {
    if (this.mode === 'sidecars') {
      return !!this.data.albumId || !!this.data.paths?.length;
    }
    return !!this.targetDir.trim();
  }

  async run(): Promise<void> {
    if (!this.canRun() || this.running()) return;
    this.running.set(true);
    try {
      const result = this.data.albumId
        ? await firstValueFrom(this.exportService.exportAlbum(this.data.albumId, this.mode, this.targetDir.trim(), this.overwrite))
        : await firstValueFrom(this.exportService.exportSidecars(this.data.paths ?? [], this.overwrite));
      const count = ('copied' in result ? result.copied : result.written) ?? 0;
      this.snackBar.open(this.i18n.t('export.done', { count }), '', { duration: 2500 });
      this.dialogRef.close(result);
    } catch {
      this.snackBar.open(this.i18n.t('export.failed'), '', { duration: 2500 });
      this.running.set(false);
    }
  }
}
