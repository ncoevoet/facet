import { Component, ElementRef, computed, inject, signal, viewChild } from '@angular/core';
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
import { ApiService } from '../../core/services/api.service';
import { I18nService } from '../../core/services/i18n.service';
import { extractErrorDetail } from '../../core/utils/http-error.util';
import { downloadBlob } from '../../shared/utils/download';
import { TranslatePipe } from '../../shared/pipes/translate.pipe';
import { I18N, I18N_KEYS } from '../../core/i18n/keys';
import type { LightroomImportResponse, LightroomManifest } from '../../core/api/types';

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

      <div class="flex flex-col gap-2 border-t pt-3 mt-1">
        <h3 class="text-sm font-medium">{{ I18N.export.lightroom.title | translate }}</h3>
        <p class="text-xs opacity-70">{{ I18N.export.lightroom.description | translate }}</p>

        <button mat-stroked-button type="button"
                [disabled]="!canDownloadManifest() || lightroomManifestRunning()"
                (click)="downloadManifest()">
          <mat-icon>download</mat-icon>
          {{ lightroomManifestRunning() ? (I18N.export.lightroom.downloading | translate) : (I18N.export.lightroom.download | translate) }}
        </button>

        <button mat-stroked-button type="button" [disabled]="lightroomImportRunning()" (click)="triggerImport()">
          <mat-icon>upload</mat-icon>
          {{ lightroomImportRunning() ? (I18N.export.lightroom.importing | translate) : (I18N.export.lightroom.import | translate) }}
        </button>
        <input #lightroomFileInput type="file" accept=".json,application/json" class="hidden"
               (change)="onImportFileSelected($event)" />

        @if (lightroomErrorDetail(); as lightroomDetail) {
          <p class="text-xs text-[var(--mat-sys-error)] opacity-80">{{ I18N.errors.server_detail | translate }} {{ lightroomDetail }}</p>
        }
      </div>
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
  private readonly api = inject(ApiService);
  private readonly lightroomFileInput = viewChild<ElementRef<HTMLInputElement>>('lightroomFileInput');

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

  // --- Lightroom manifest download / reverse-sync import ---
  //
  // Same scope as `runRequest`'s sidecar-export branches (Orchestrator
  // adjudication, Step 11 of lightroom-flow-improvements.md): explicit paths,
  // a view-scoped filter set, or -- when the dialog only carries an
  // `albumId` -- the gallery's own `album_id` filter key, which the scope
  // resolver both `/api/export/sidecars` and `/api/lightroom/manifest` share
  // (`_selected_paths` / `api/routers/gallery.py`'s `_scoped_album_id`)
  // already understands. That key exists and is server-supported, so the
  // album case is NOT disabled here -- it is translated into a filter.

  readonly lightroomManifestRunning = signal(false);
  readonly lightroomImportRunning = signal(false);
  readonly lightroomErrorDetail = signal<string | null>(null);

  readonly lightroomScope = computed<
    { paths?: string[]; filters?: Record<string, string>; exclude?: string[] } | null
  >(() => {
    if (this.data.paths?.length) return { paths: this.data.paths };
    if (this.data.filters) return { filters: this.data.filters, exclude: this.data.exclude ?? [] };
    if (this.data.albumId) return { filters: { album_id: String(this.data.albumId) } };
    return null;
  });

  readonly canDownloadManifest = computed(() => this.lightroomScope() !== null);

  async downloadManifest(): Promise<void> {
    const scope = this.lightroomScope();
    if (!scope || this.lightroomManifestRunning()) return;
    this.lightroomManifestRunning.set(true);
    this.lightroomErrorDetail.set(null);
    try {
      const manifest = await firstValueFrom(
        this.api.post<LightroomManifest>('/lightroom/manifest', scope),
      );
      downloadBlob(
        new Blob([JSON.stringify(manifest, null, 2)], { type: 'application/json' }),
        'facet_manifest.json',
      );
      if ((manifest.pending_corrections ?? 0) > 0) {
        this.snackBar.open(
          this.i18n.t(I18N.export.lightroom.pending_corrections, { count: manifest.pending_corrections }),
          '', { duration: 6000 },
        );
      }
    } catch (error) {
      this.lightroomErrorDetail.set(extractErrorDetail(error) ?? null);
      this.snackBar.open(this.i18n.t(I18N.export.lightroom.download_failed), '', { duration: 2500 });
    } finally {
      this.lightroomManifestRunning.set(false);
    }
  }

  triggerImport(): void {
    this.lightroomFileInput()?.nativeElement.click();
  }

  async onImportFileSelected(event: Event): Promise<void> {
    const input = event.target as HTMLInputElement;
    const file = input.files?.[0];
    input.value = '';
    if (!file) return;

    let parsed: unknown;
    try {
      parsed = JSON.parse(await file.text());
    } catch {
      this.snackBar.open(this.i18n.t(I18N.export.lightroom.invalid_json), '', { duration: 3000 });
      return;
    }

    this.lightroomImportRunning.set(true);
    this.lightroomErrorDetail.set(null);
    try {
      const result = await firstValueFrom(
        this.api.post<LightroomImportResponse>('/lightroom/import', parsed),
      );
      this.snackBar.open(
        this.i18n.t(I18N.export.lightroom.imported, {
          matched: result.matched, unmatched: result.unmatched, changed: result.changed,
        }),
        '', { duration: 4000 },
      );
    } catch (error) {
      this.lightroomErrorDetail.set(extractErrorDetail(error) ?? null);
      this.snackBar.open(this.i18n.t(I18N.export.lightroom.import_failed), '', { duration: 2500 });
    } finally {
      this.lightroomImportRunning.set(false);
    }
  }
}
