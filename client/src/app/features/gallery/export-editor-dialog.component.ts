import { Component, computed, inject, signal } from '@angular/core';
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
import {
  AlbumExportMode, AlbumExportResult, ExportService, SidecarExportResult,
} from '../../core/services/export.service';
import { I18nService } from '../../core/services/i18n.service';
import { extractErrorDetail } from '../../core/utils/http-error.util';
import { TranslatePipe } from '../../shared/pipes/translate.pipe';
import { I18N, I18N_KEYS } from '../../core/i18n/keys';

export interface ExportEditorDialogData {
  /** Explicit selected photo paths (gallery selection). */
  paths?: string[];
  /** The whole current gallery view, when the selection is view-scoped: the
   *  server derives the rows from it, so no path list is sent and the
   *  endpoint's 10,000-path cap does not apply. Mutually exclusive with `paths`. */
  filters?: Record<string, string> | null;
  /** Photos unticked out of a view-scoped selection. */
  exclude?: string[];
  /** How many photos a view-scoped selection stands for (display only). */
  count?: number;
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
    <h2 mat-dialog-title>{{ I18N.export.title | translate }}</h2>
    <mat-dialog-content class="flex flex-col gap-3">
      <p class="text-sm opacity-80">{{ I18N.export.description | translate }}</p>

      @if (count) {
        <p class="text-sm opacity-70">{{ count }} {{ I18N.cull.selected | translate }}</p>
      }

      <mat-radio-group [ngModel]="mode()" (ngModelChange)="mode.set($event)" class="flex flex-col gap-2">
        <mat-radio-button value="sidecars">{{ I18N.export.mode_sidecars | translate }}</mat-radio-button>
        @if (data.albumId) {
          <mat-radio-button value="copy">{{ I18N.export.mode_copy | translate }}</mat-radio-button>
          <mat-radio-button value="symlink">{{ I18N.export.mode_symlink | translate }}</mat-radio-button>
        }
      </mat-radio-group>

      @if (mode() === 'sidecars') {
        <mat-checkbox [ngModel]="overwrite()" (ngModelChange)="overwrite.set($event)">{{ I18N.export.overwrite | translate }}</mat-checkbox>
        <p class="text-xs opacity-60">{{ I18N.export.overwrite_hint | translate }}</p>
      } @else {
        <mat-form-field class="w-full">
          <mat-label>{{ I18N.export.target_dir | translate }}</mat-label>
          <input matInput [ngModel]="targetDir()" (ngModelChange)="targetDir.set($event); errorDetail.set(null)" />
        </mat-form-field>
      }

      @if (errorDetail(); as detail) {
        <p class="text-sm text-[var(--mat-sys-error)]">{{ I18N.export.failed | translate }}</p>
        <p class="text-xs text-[var(--mat-sys-error)] opacity-80">{{ I18N.errors.server_detail | translate }} {{ detail }}</p>
      }
    </mat-dialog-content>
    <mat-dialog-actions align="end">
      <button mat-button mat-dialog-close>{{ I18N.ui.buttons.cancel | translate }}</button>
      <button mat-flat-button [disabled]="!canRun() || running()" (click)="run()">
        @if (running()) { <mat-spinner diameter="18" class="!inline-block !align-baseline" [attr.aria-label]="I18N.ui.labels.loading | translate" ></mat-spinner> }
        {{ running() ? (I18N.export.running | translate) : (I18N.export.run | translate) }}
      </button>
    </mat-dialog-actions>
  `,
})
export class ExportEditorDialogComponent {
  protected readonly I18N = I18N_KEYS;
  protected readonly data = inject<ExportEditorDialogData>(MAT_DIALOG_DATA);
  private readonly exportService = inject(ExportService);
  private readonly dialogRef = inject(MatDialogRef<ExportEditorDialogComponent>);
  private readonly snackBar = inject(MatSnackBar);
  private readonly i18n = inject(I18nService);

  /**
   * How many photos the run will touch, or 0 when only the server knows.
   *
   * A view-scoped selection sends a filter rather than a path list, so its size
   * arrives as `count` — same as the cull dialog, which is the other dialog a
   * whole-view selection opens, and which states the same number in the same
   * words. An album export has no client-side count at all: the rows are the
   * album's, whatever they are, so it states none rather than a wrong one.
   */
  protected readonly count = this.data.count ?? this.data.paths?.length ?? 0;

  readonly mode = signal<AlbumExportMode>('sidecars');
  readonly overwrite = signal(false);
  readonly targetDir = signal('');
  readonly running = signal(false);
  readonly errorDetail = signal<string | null>(null);

  readonly canRun = computed(() => {
    if (this.mode() === 'sidecars') {
      return !!this.data.albumId || !!this.data.paths?.length || !!this.data.filters;
    }
    return !!this.targetDir().trim();
  });

  /**
   * The one request this dialog makes.
   *
   * A view-scoped selection takes its own service method rather than the
   * path-list one, because the path list is exactly what that scope exists to
   * avoid materialising.
   */
  private runRequest(): Promise<AlbumExportResult | SidecarExportResult> {
    if (this.data.albumId) {
      return firstValueFrom(
        this.exportService.exportAlbum(this.data.albumId, this.mode(), this.targetDir().trim(), this.overwrite()),
      );
    }
    if (this.data.filters) {
      return firstValueFrom(this.exportService.exportSidecarsForView(
        this.data.filters, this.data.exclude ?? [], this.overwrite(),
      ));
    }
    return firstValueFrom(this.exportService.exportSidecars(this.data.paths ?? [], this.overwrite()));
  }

  async run(): Promise<void> {
    if (!this.canRun() || this.running()) return;
    this.running.set(true);
    this.errorDetail.set(null);
    try {
      const result = await this.runRequest();
      const count = ('copied' in result ? result.copied : result.written) ?? 0;
      this.snackBar.open(this.i18n.t(I18N.export.done, { count }), '', { duration: 2500 });
      this.dialogRef.close(result);
    } catch (error) {
      this.errorDetail.set(extractErrorDetail(error) ?? null);
      this.snackBar.open(this.i18n.t(I18N.export.failed), '', { duration: 2500 });
      this.running.set(false);
    }
  }
}
