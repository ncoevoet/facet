import { Component, ElementRef, computed, inject, signal, viewChild, ChangeDetectionStrategy, DestroyRef, effect, untracked } from '@angular/core';
import { HttpErrorResponse } from '@angular/common/http';
import { DatePipe } from '@angular/common';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { Router, NavigationStart } from '@angular/router';
import { FormsModule } from '@angular/forms';
import { MAT_DIALOG_DATA, MatDialogModule, MatDialogRef } from '@angular/material/dialog';
import { MatFormFieldModule } from '@angular/material/form-field';
import { MatInputModule } from '@angular/material/input';
import { MatButtonModule } from '@angular/material/button';
import { MatCheckboxModule } from '@angular/material/checkbox';
import { MatRadioModule } from '@angular/material/radio';
import { MatIconModule } from '@angular/material/icon';
import { MatProgressSpinnerModule } from '@angular/material/progress-spinner';
import { MatProgressBarModule } from '@angular/material/progress-bar';
import { MatSnackBar } from '@angular/material/snack-bar';
import { firstValueFrom, Subject, takeUntil } from 'rxjs';
import {
  AlbumExportMode, AlbumExportResult, ExportService, SidecarJobStatus, SidecarJobScope,
} from '../../core/services/export.service';
import { AuthService } from '../../core/services/auth.service';
import { pathOf } from '../../shared/utils/url-path';
import { ApiService } from '../../core/services/api.service';
import { I18nService } from '../../core/services/i18n.service';
import { extractErrorDetail } from '../../core/utils/http-error.util';
import { downloadBlob } from '../../shared/utils/download';
import { TranslatePipe } from '../../shared/pipes/translate.pipe';
import { I18N, i18nKeys } from '../../core/i18n/keys';
import type { LightroomImportResponse, LightroomManifest } from '../../core/api/types';
import { SidecarJobLabelPipe } from './sidecar-job-label.pipe';

export interface ExportEditorDialogData {
  receiptsOnly?: boolean;
  /** Explicit selected photo paths (gallery selection). */
  paths?: string[];
  /** The whole current gallery view, when the selection is view-scoped: the
   *  server derives the rows from it, so no path list is sent and the
   *  path and filter scopes are both capped at 10,000 photos. Mutually exclusive with `paths`. */
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
    MatProgressSpinnerModule, MatProgressBarModule, DatePipe, TranslatePipe, SidecarJobLabelPipe,
  ],
  changeDetection: ChangeDetectionStrategy.Eager,
  template: `
    <h2 mat-dialog-title>{{ (data.receiptsOnly ? I18N.export.jobs.workspace_title : I18N.export.title) | translate }}</h2>
    <mat-dialog-content class="flex flex-col gap-3">
      <p class="text-sm opacity-80">{{ (data.receiptsOnly ? I18N.export.jobs.workspace_hint : I18N.export.description) | translate }}</p>

      @if (!data.receiptsOnly) {
      @if (count) {
        <p class="text-sm opacity-70">{{ count }} {{ I18N.cull.selected | translate }}</p>
      }

      <mat-radio-group [disabled]="running()" [ngModel]="mode()" (ngModelChange)="mode.set($event)" class="flex flex-col gap-2">
        <mat-radio-button value="sidecars">{{ I18N.export.mode_sidecars | translate }}</mat-radio-button>
        @if (data.albumId) {
          <mat-radio-button value="copy">{{ I18N.export.mode_copy | translate }}</mat-radio-button>
          <mat-radio-button value="symlink">{{ I18N.export.mode_symlink | translate }}</mat-radio-button>
        }
      </mat-radio-group>

      @if (mode() === 'sidecars') {
        <mat-checkbox [disabled]="running()" [ngModel]="overwrite()" (ngModelChange)="overwrite.set($event)">{{ I18N.export.overwrite | translate }}</mat-checkbox>
        <p class="text-xs opacity-60">{{ I18N.export.overwrite_hint | translate }}</p>
      } @else {
        <mat-form-field class="w-full">
          <mat-label>{{ I18N.export.target_dir | translate }}</mat-label>
          <input matInput [ngModel]="targetDir()" (ngModelChange)="targetDir.set($event); errorDetail.set(null)" />
        </mat-form-field>
      }

      @if (errorDetail(); as detail) {
        <p class="text-sm text-[var(--mat-sys-error)]">{{ (readError() ? I18N.export.jobs.read_failed : I18N.export.failed) | translate }}</p>
        <p class="text-xs text-[var(--mat-sys-error)] opacity-80">{{ I18N.errors.server_detail | translate }} {{ detail }}</p>
      }
      }
      @if (data.receiptsOnly && errorDetail(); as detail) { <p role="alert">{{ detail }}</p> }

      @if (job(); as current) {
        <section class="flex flex-col gap-2 border-t pt-3">
          <h3 class="text-sm font-medium" aria-live="polite" aria-atomic="true">{{ current | sidecarJobLabel | translate }}</h3>
          <p class="m-0 break-all font-mono text-xs">{{ I18N.export.jobs.receipt_id | translate }}: {{ current.id }}</p>
          <p class="text-sm">{{ I18N.export.jobs.progress | translate:{ processed: current.processed, total: current.total } }}</p>
          <mat-progress-bar mode="determinate" [value]="progressPercent()"
            [attr.aria-label]="I18N.export.jobs.progress | translate:{ processed: current.processed, total: current.total }" />
          <p class="text-sm">{{ I18N.export.jobs.counts | translate:{ written: current.written, skipped: current.skipped, errors: current.errors } }}</p>
          @if (current.first_error_code; as errorCode) { <p class="text-xs text-[var(--mat-sys-error)]">{{ errorKeys[errorCode] | translate }}</p> }
          @else if (current.first_error) { <p class="text-xs text-[var(--mat-sys-error)]">{{ current.first_error }}</p> }
          @if (current.state === 'running') {
            <p class="text-xs opacity-70">{{ I18N.export.jobs.close_hint | translate }}</p>
            <button mat-stroked-button [disabled]="submitting() || readingStatus() || current.cancel_requested" (click)="cancelJob()">
              {{ (current.cancel_requested ? I18N.export.jobs.cancelling : I18N.export.jobs.cancel) | translate }}
            </button>
            <p class="text-xs opacity-70">{{ I18N.export.jobs.cancel_hint | translate }}</p>
          }
          @if (canRetry()) {
            <button mat-stroked-button [disabled]="running() || readingStatus()" (click)="retryJob()">{{ I18N.export.jobs.retry | translate }}</button>
            <p class="text-xs opacity-70">{{ I18N.export.jobs.retry_hint | translate }}</p>
          }
          <button mat-button [disabled]="submitting()" (click)="viewJob(current)">{{ I18N.export.jobs.refresh | translate }}</button>
        </section>
      }

      <section class="flex flex-col gap-2 border-t pt-3">
        <div class="flex items-center justify-between gap-2">
          <h3 class="text-sm font-medium">{{ I18N.export.jobs.recent | translate }}</h3>
          <button mat-button [disabled]="recentLoading()"
                  [attr.aria-label]="(I18N.export.jobs.refresh | translate) + ': ' + (I18N.export.jobs.recent | translate)"
                  (click)="loadRecent()">{{ I18N.export.jobs.refresh | translate }}</button>
        </div>
        @for (receipt of recentJobs(); track receipt.id) {
          <button mat-stroked-button class="!justify-start" [disabled]="submitting()"
                  [attr.aria-current]="job()?.id === receipt.id ? 'true' : null" (click)="viewJob(receipt)">
            {{ receipt.started_at * 1000 | date:'dd/MM/yyyy HH:mm' }} · {{ receipt | sidecarJobLabel | translate }} · {{ receipt.processed }}/{{ receipt.total }}
          </button>
        }
        @if (!recentJobs().length && !recentLoading() && !errorDetail()) { <p class="text-xs opacity-70">{{ I18N.export.jobs.none | translate }}</p> }
      </section>

      @if (!data.receiptsOnly) {
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
      }
    </mat-dialog-content>
    <mat-dialog-actions align="end">
      <button mat-button (click)="close()">{{ I18N.export.jobs.close | translate }}</button>
      @if (!data.receiptsOnly) {
      <button mat-flat-button [disabled]="!canRun() || running() || readingStatus()" (click)="run()">
        @if (running()) { <mat-spinner diameter="18" class="!inline-block !align-baseline" [attr.aria-label]="I18N.ui.labels.loading | translate" ></mat-spinner> }
        {{ running() ? (I18N.export.running | translate) : (I18N.export.run | translate) }}
      </button>
      }
    </mat-dialog-actions>
  `,
})
export class ExportEditorDialogComponent {
  protected readonly I18N = i18nKeys();
  protected readonly data = inject<ExportEditorDialogData>(MAT_DIALOG_DATA);
  private readonly exportService = inject(ExportService);
  private readonly dialogRef = inject(MatDialogRef<ExportEditorDialogComponent>);
  private readonly snackBar = inject(MatSnackBar);
  private readonly i18n = inject(I18nService);
  private readonly api = inject(ApiService);
  private readonly auth = inject(AuthService);
  private readonly router = inject(Router);
  private readonly destroyRef = inject(DestroyRef);
  private readonly owner = this.auth.identity();
  private readonly readsStopped = new Subject<void>();
  private watching = 0;
  private attached = true;
  private pollTimer: ReturnType<typeof setTimeout> | null = null;
  private closeOnSuccess = false;
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
  readonly submitting = signal(false);
  readonly job = signal<SidecarJobStatus | null>(null);
  readonly recentJobs = signal<SidecarJobStatus[]>([]);
  readonly recentLoading = signal(false);
  readonly readingStatus = signal(false);
  readonly running = computed(() => this.submitting() || this.job()?.state === 'running');
  readonly progressPercent = computed(() => {
    const job = this.job();
    return job?.total ? Math.floor(job.processed / job.total * 100) : 0;
  });
  readonly canRetry = computed(() => {
    const job = this.job();
    return !!job && job.state !== 'running'
      && (job.errors > 0 || job.skipped > 0 || job.processed < job.total || job.state === 'interrupted');
  });
  readonly errorKeys = {
    metadata_repair: I18N.export.jobs.errors.metadata_repair, write_failed: I18N.export.jobs.errors.write_failed,
    exiftool_upgrade: I18N.export.jobs.errors.exiftool_upgrade, stopped: I18N.export.jobs.errors.stopped,
  };
  readonly errorDetail = signal<string | null>(null);
  readonly readError = signal(false);

  readonly canRun = computed(() => {
    if (this.data.receiptsOnly) return false;
    if (this.auth.identity() !== this.owner || !this.auth.isEdition()) return false;
    if (this.mode() === 'sidecars') {
      return !!this.data.albumId || !!this.data.paths?.length || !!this.data.filters;
    }
    return !!this.data.albumId && !!this.targetDir().trim();
  });

  constructor() {
    this.destroyRef.onDestroy(() => this.detach());
    this.dialogRef.beforeClosed().pipe(takeUntilDestroyed(this.destroyRef)).subscribe(() => this.detach());
    effect(() => {
      const identity = this.auth.identity();
      const edition = this.auth.isEdition();
      if (identity !== this.owner || !edition) untracked(() => {
        this.job.set(null);
        this.recentJobs.set([]);
        this.errorDetail.set(null);
        this.lightroomErrorDetail.set(null);
        this.close();
      });
    });
    this.router.events.pipe(takeUntilDestroyed(this.destroyRef)).subscribe(event => {
      if (event instanceof NavigationStart && pathOf(event.url) !== pathOf(this.router.url)) this.close();
    });
    void this.loadRecent();
  }

  private current(seq = this.watching): boolean {
    return this.attached && !this.destroyRef.destroyed && this.auth.identity() === this.owner
      && this.auth.isEdition() && seq === this.watching;
  }

  private stopReads(): number {
    this.watching++;
    this.readsStopped.next();
    if (this.pollTimer !== null) clearTimeout(this.pollTimer);
    this.pollTimer = null;
    return this.watching;
  }

  private detach(): void {
    this.attached = false;
    this.submitting.set(false);
    this.recentLoading.set(false);
    this.readingStatus.set(false);
    this.stopReads();
  }

  close(result?: AlbumExportResult | SidecarJobStatus): void {
    this.detach();
    this.dialogRef.close(result);
  }

  async loadRecent(): Promise<void> {
    if (!this.current() || this.recentLoading()) return;
    const seq = this.watching;
    this.recentLoading.set(true);
    try {
      const jobs = await firstValueFrom(this.exportService.recentSidecarJobs().pipe(takeUntil(this.readsStopped)));
      if (this.current(seq)) { this.readError.set(false); this.errorDetail.set(null); this.recentJobs.set(jobs); }
    } catch (error) {
      if (this.current(seq)) { this.readError.set(true); this.errorDetail.set(extractErrorDetail(error) ?? this.i18n.t(I18N.export.jobs.read_failed)); }
    } finally {
      if (this.current()) this.recentLoading.set(false);
    }
  }

  private acceptJob(job: SidecarJobStatus): void {
    this.job.set(job);
    this.recentJobs.update(jobs => [job, ...jobs.filter(old => old.id !== job.id)].slice(0, 20));
    if (job.state === 'running') this.schedulePoll(job.id);
    else if (this.closeOnSuccess && job.state === 'completed' && job.errors === 0 && job.skipped === 0 && job.processed === job.total) {
      this.snackBar.open(this.i18n.t(I18N.export.done, { count: job.written }), '', { duration: 2500 });
      this.close(job);
    }
  }

  private schedulePoll(id: string, delay = 1000): void {
    if (this.pollTimer !== null) clearTimeout(this.pollTimer);
    const seq = this.watching;
    this.pollTimer = setTimeout(() => {
      this.pollTimer = null;
      void this.readJob(id, seq);
    }, delay);
  }

  private async readJob(id: string, seq: number): Promise<void> {
    if (!this.current(seq)) return;
    try {
      const job = await firstValueFrom(this.exportService.sidecarJob(id).pipe(takeUntil(this.readsStopped)));
      if (this.current(seq)) { this.readError.set(false); this.errorDetail.set(null); this.acceptJob(job); }
    } catch (error) {
      if (this.current(seq)) {
        this.readError.set(true);
        this.errorDetail.set(extractErrorDetail(error) ?? this.i18n.t(I18N.export.jobs.read_failed));
        // Retry only this read after a quiet interval. Mutation retries remain explicit.
        if (error instanceof HttpErrorResponse && (error.status === 0 || error.status === 429 || error.status >= 500)) {
          this.schedulePoll(id, 5000);
        }
      }
    }
  }

  async viewJob(job: SidecarJobStatus): Promise<void> {
    if (!this.current() || this.submitting()) return;
    this.closeOnSuccess = false;
    const seq = this.stopReads();
    this.readingStatus.set(true);
    try { await this.readJob(job.id, seq); }
    finally { if (this.current(seq)) this.readingStatus.set(false); }
  }

  async cancelJob(): Promise<void> {
    const job = this.job();
    if (!this.current() || this.readingStatus() || this.submitting() || job?.state !== 'running' || job.cancel_requested) return;
    const seq = this.stopReads();
    this.submitting.set(true);
    this.readError.set(false);
    try {
      const status = await firstValueFrom(this.exportService.cancelSidecarJob(job.id));
      if (this.current(seq)) this.acceptJob(status);
    } catch (error) {
      if (this.current(seq)) this.errorDetail.set(extractErrorDetail(error) ?? this.i18n.t(I18N.export.failed));
    } finally {
      if (this.current(seq)) this.submitting.set(false);
    }
  }

  async retryJob(): Promise<void> {
    const job = this.job();
    if (!this.current() || this.readingStatus() || this.running() || !this.canRetry() || !job) return;
    const seq = this.stopReads();
    this.submitting.set(true);
    this.readError.set(false);
    this.errorDetail.set(null);
    try {
      const status = await firstValueFrom(this.exportService.retrySidecarJob(job.id));
      if (this.current(seq)) { this.closeOnSuccess = !this.data.receiptsOnly; this.acceptJob(status); }
    } catch (error) {
      if (this.current(seq)) this.errorDetail.set(extractErrorDetail(error) ?? this.i18n.t(I18N.export.failed));
    } finally {
      if (this.current(seq)) this.submitting.set(false);
    }
  }

  async run(): Promise<void> {
    if (!this.current() || this.readingStatus() || !this.canRun() || this.running()) return;
    const seq = this.stopReads();
    this.submitting.set(true);
    this.readError.set(false);
    this.errorDetail.set(null);
    try {
      if (this.mode() === 'sidecars') {
        const scope = this.lightroomScope();
        if (!scope) return;
        const result = await firstValueFrom(this.exportService.startSidecarJob(scope, this.overwrite()));
        if (this.current(seq)) { this.closeOnSuccess = true; this.acceptJob(result); }
      } else {
        const result = await firstValueFrom(this.exportService.exportAlbum(this.data.albumId!, this.mode(), this.targetDir().trim(), this.overwrite()));
        if (!this.current(seq)) return;
        this.snackBar.open(this.i18n.t(I18N.export.done, { count: result.copied ?? result.written ?? 0 }), '', { duration: 2500 });
        this.close(result);
      }
    } catch (error) {
      if (!this.current(seq)) return;
      this.errorDetail.set(extractErrorDetail(error) ?? null);
      this.snackBar.open(this.i18n.t(I18N.export.failed), '', { duration: 2500 });
    } finally {
      if (this.current(seq)) this.submitting.set(false);
    }
  }

  // --- Lightroom manifest download / reverse-sync import ---
  //
  // Lightroom and sidecar jobs share the same path/filter/album scope.
  // The server resolves album_id with its visibility and smart-filter checks.

  readonly lightroomManifestRunning = signal(false);
  readonly lightroomImportRunning = signal(false);
  readonly lightroomErrorDetail = signal<string | null>(null);

  readonly lightroomScope = computed<SidecarJobScope | null>(() => {
    if (this.data.paths?.length) return { paths: this.data.paths };
    if (this.data.filters) return { filters: this.data.filters, exclude: this.data.exclude ?? [] };
    if (this.data.albumId) return { filters: { album_id: String(this.data.albumId) } };
    return null;
  });

  readonly canDownloadManifest = computed(() => this.lightroomScope() !== null);

  async downloadManifest(): Promise<void> {
    const scope = this.lightroomScope();
    if (!this.current() || !scope || this.lightroomManifestRunning()) return;
    const seq = this.watching;
    this.lightroomManifestRunning.set(true);
    this.lightroomErrorDetail.set(null);
    try {
      const manifest = await firstValueFrom(
        this.api.post<LightroomManifest>('/lightroom/manifest', scope).pipe(takeUntil(this.readsStopped)),
      );
      if (!this.current(seq)) return;
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
      if (!this.current(seq)) return;
      this.lightroomErrorDetail.set(extractErrorDetail(error) ?? null);
      this.snackBar.open(this.i18n.t(I18N.export.lightroom.download_failed), '', { duration: 2500 });
    } finally {
      this.lightroomManifestRunning.set(false);
    }
  }

  triggerImport(): void {
    if (this.current()) this.lightroomFileInput()?.nativeElement.click();
  }

  async onImportFileSelected(event: Event): Promise<void> {
    const input = event.target as HTMLInputElement;
    const file = input.files?.[0];
    input.value = '';
    if (!file || !this.current()) return;
    const seq = this.watching;

    let parsed: unknown;
    try {
      parsed = JSON.parse(await file.text());
    } catch {
      if (!this.current(seq)) return;
      this.snackBar.open(this.i18n.t(I18N.export.lightroom.invalid_json), '', { duration: 3000 });
      return;
    }

    if (!this.current(seq)) return;
    this.lightroomImportRunning.set(true);
    this.lightroomErrorDetail.set(null);
    try {
      const result = await firstValueFrom(
        this.api.post<LightroomImportResponse>('/lightroom/import', parsed),
      );
      if (!this.current(seq)) return;
      this.snackBar.open(
        this.i18n.t(I18N.export.lightroom.imported, {
          matched: result.matched, unmatched: result.unmatched, changed: result.changed,
        }),
        '', { duration: 4000 },
      );
    } catch (error) {
      if (!this.current(seq)) return;
      this.lightroomErrorDetail.set(extractErrorDetail(error) ?? null);
      this.snackBar.open(this.i18n.t(I18N.export.lightroom.import_failed), '', { duration: 2500 });
    } finally {
      this.lightroomImportRunning.set(false);
    }
  }
}
