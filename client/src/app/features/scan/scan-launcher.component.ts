import { ChangeDetectionStrategy, Component, OnInit, computed, effect, inject, signal } from '@angular/core';
import { HttpErrorResponse } from '@angular/common/http';
import { MatDialogRef, MatDialogModule } from '@angular/material/dialog';
import { MatButtonModule } from '@angular/material/button';
import { MatIconModule } from '@angular/material/icon';
import { MatProgressBarModule } from '@angular/material/progress-bar';
import { ScanService, ScanDirectory } from '../../core/services/scan.service';
import { TranslatePipe } from '../../shared/pipes/translate.pipe';
import { I18N, i18nKeys } from '../../core/i18n/keys';
import { ScanHistoryComponent } from './scan-history.component';

/**
 * Superadmin-only dialog to pick a configured directory and launch + watch a
 * scoring scan in-app. Binds the live ScanService status (SSE with polling
 * fallback) to a progress bar and an output tail, and closes with `true` once
 * the scan finishes cleanly so the gallery can refresh.
 */
/** Statuses that prove the server refused the start, so no scan is running. */
const DEFINITE_REFUSALS = new Set([400, 403, 409]);

@Component({
  selector: 'app-scan-launcher',
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [MatDialogModule, MatButtonModule, MatIconModule, MatProgressBarModule, TranslatePipe, ScanHistoryComponent],
  template: `
    <h2 mat-dialog-title>{{ I18N.scan.title | translate }}</h2>
    <mat-dialog-content class="!pt-2 min-w-0 w-full max-w-[34rem]">
      @if (observationError()) {
        <p role="alert" class="text-sm">{{ I18N.scan.status_unavailable | translate }}</p>
        <button mat-stroked-button (click)="retryStatus()">{{ I18N.scan.retry_status | translate }}</button>
      } @else if (!statusKnown()) {
        <p role="status" class="text-sm">{{ I18N.scan.checking_status | translate }}</p>
      }
      @if (startRefusal(); as refusal) {
        <p role="alert" class="text-sm">{{ refusal.detail ?? (refusal.key! | translate) }}</p>
      } @else if (startError()) {
        <p role="alert" class="text-sm">{{ I18N.scan.start_unconfirmed | translate }}</p>
      }
      @if (stopError()) { <p role="alert" class="text-sm">{{ I18N.scan.stop_unconfirmed | translate }}</p> }
      @if (!started()) {
        @if (loadingDirs()) {
          <p class="text-[var(--mat-sys-on-surface-variant)] text-sm py-4">{{ I18N.scan.loading_directories | translate }}</p>
        } @else if (dirLoadError()) {
          <div class="flex items-center gap-2 text-red-400 text-sm py-4">
            <mat-icon class="!text-base !w-4 !h-4">error_outline</mat-icon>
            <span>{{ I18N.notifications.connection_error | translate }}</span>
          </div>
        } @else if (directories().length === 0) {
          <p class="text-[var(--mat-sys-on-surface-variant)] text-sm py-4">{{ I18N.scan.no_directories | translate }}</p>
        } @else {
          <p class="text-sm text-[var(--mat-sys-on-surface-variant)] mb-2">{{ I18N.scan.pick_directory | translate }}</p>
          <div class="flex flex-col gap-1 max-h-64 overflow-y-auto">
            @for (dir of directories(); track dir.path) {
              <label class="flex items-center gap-2 px-2 py-1.5 rounded cursor-pointer hover:bg-[var(--mat-sys-surface-container-high)]">
                <input type="radio" name="scanDir" [value]="dir.path"
                       [checked]="selectedDir() === dir.path"
                       (change)="selectedDir.set(dir.path)" />
                <span class="text-sm font-mono truncate">{{ dir.path }}</span>
              </label>
            }
          </div>
        }
      } @else {
        <div class="flex items-center gap-2 mb-2 text-sm">
          <mat-icon class="!text-base !w-4 !h-4" [class.text-[var(--facet-positive)]]="connected() && statusKnown() && !observationError()">
            {{ connected() && statusKnown() && !observationError() ? 'cloud_done' : 'sync' }}
          </mat-icon>
          <span class="opacity-80">
            @if (phaseLabelKey(); as key) { {{ key | translate }} }
            @else { {{ status().progress?.phase }} }
          </span>
          @if (eta() !== null) {
            <span class="text-[var(--mat-sys-on-surface-variant)] ml-auto">{{ I18N.scan.eta | translate }} {{ eta() }}s</span>
          }
        </div>
        @if (statusKnown() && status().running && !observationError()) {
          <mat-progress-bar [mode]="progressValue() === null ? 'indeterminate' : 'determinate'"
                            [value]="progressValue() ?? 0" />
        }
        @if ((!statusKnown() || observationError()) && outputTail()) {
          <p class="mt-3 mb-1 text-xs">{{ I18N.scan.last_observed_output | translate }}</p>
        }
        <pre class="mt-3 text-xs font-mono whitespace-pre-wrap max-h-48 overflow-y-auto opacity-70 bg-[var(--mat-sys-surface-container)] rounded p-2">{{ outputTail() }}</pre>
      }
      <app-scan-history (retrySubmitted)="noteRetrySubmitted()" (retryAccepted)="noteRetryAccepted($event)" />
      @if (pendingStopId()) {
        <section class="mt-3 border-t border-[var(--mat-sys-outline-variant)] pt-2" [attr.aria-label]="I18N.scan.stop_confirm | translate">
          <p class="text-sm">{{ I18N.scan.stop_consequence | translate }}</p>
          <button mat-button (click)="pendingStopId.set(null)" [disabled]="stopping()">{{ I18N.ui.buttons.cancel | translate }}</button>
          <button mat-stroked-button (click)="confirmStop()" [disabled]="stopping()">{{ I18N.scan.stop_confirm | translate }}</button>
        </section>
      }
    </mat-dialog-content>
    <mat-dialog-actions align="end">
      <button mat-button [mat-dialog-close]="(sawRunning || retryExitObserved()) && statusKnown() && !observationError() && !status().running && status().exit_code !== null">{{ I18N.scan.close | translate }}</button>
      @if (canCancel() && !pendingStopId()) {
        <button mat-button (click)="askStop()" [disabled]="stopping()">{{ I18N.scan.stop_button | translate }}</button>
      }
      @if (!started()) {
        <button mat-flat-button color="primary"
                [disabled]="!selectedDir() || !statusKnown() || observationError() || status().running"
                data-scan-start (click)="start()">
          {{ I18N.scan.start_button | translate }}
        </button>
      }
    </mat-dialog-actions>
  `,
})
export class ScanLauncherComponent implements OnInit {
  protected readonly I18N = i18nKeys();
  private readonly scan = inject(ScanService);
  private readonly dialogRef = inject(MatDialogRef<ScanLauncherComponent>);

  protected readonly directories = signal<ScanDirectory[]>([]);
  protected readonly selectedDir = signal<string | null>(null);
  protected readonly loadingDirs = signal(true);
  protected readonly dirLoadError = signal(false);
  protected readonly started = signal(false);
  protected readonly startError = signal(false);
  /** A start the server answered with a refusal: nothing is running, so the
   *  reason is shown and the Start button comes back. */
  protected readonly startRefusal = signal<{ detail?: string; key?: string } | null>(null);
  protected readonly stopError = signal(false);
  protected readonly stopping = signal(false);
  protected readonly pendingStopId = signal<string | null>(null);
  protected readonly canCancel = this.scan.canCancel;

  protected readonly status = this.scan.status;
  protected readonly connected = this.scan.connected;
  protected readonly statusKnown = this.scan.statusKnown;
  protected readonly observationError = this.scan.observationError;
  // ScanService is a root singleton; its status can still hold a prior run's
  // {running:false, exit_code:0}. Only auto-close once THIS run was seen live.
  protected sawRunning = false;
  private readonly retryMode = signal(false);
  protected readonly acceptedRetryJob = signal<string | null>(null);
  protected readonly retryExitObserved = computed(() => this.acceptedRetryJob() !== null && this.acceptedRetryJob() === this.status().job_id);
  private stopTargetId: string | null = null;

  protected readonly progressValue = computed(() => {
    const p = this.status().progress;
    if (!p || !p.total) return null;
    return Math.round(((p.current ?? 0) / p.total) * 100);
  });
  protected readonly phaseLabelKey = computed(() => {
    if (this.observationError()) return I18N.scan.status_unknown;
    if (!this.statusKnown()) return I18N.scan.checking_status;
    if (this.status().cancel_requested) return this.status().running ? I18N.scan.stopping : I18N.scan.ended_after_stop;
    if (!this.status().running && this.status().exit_code !== null && this.status().exit_code !== 0) return I18N.scan.failed;
    if (!this.status().running) return this.status().exit_code === 0 ? I18N.scan.completed : I18N.scan.stopped;
    const phase = this.status().progress?.phase;
    if (!phase) return I18N.scan.running;
    return Object.hasOwn(I18N.scan.phase, phase)
      ? (I18N.scan.phase as Record<string, string>)[phase] : null;
  });
  protected readonly eta = computed(() => this.statusKnown() && !this.observationError() && this.status().running && !this.status().cancel_requested
    ? this.status().progress?.eta_seconds ?? null : null);
  protected readonly outputTail = computed(() => this.status().output.slice(-20).join('\n'));

  constructor() {
    // Close with success once THIS run was observed running and then finished
    // cleanly — guarding against a stale prior-run success in the shared signal.
    effect(() => {
      const s = this.status();
      if (this.pendingStopId() && (!this.canCancel() || this.pendingStopId() !== s.job_id)) this.pendingStopId.set(null);
      if (!this.statusKnown() || this.observationError()) return;
      if (this.stopError() && s.job_id && (s.job_id !== this.stopTargetId || s.cancel_requested)) this.stopError.set(false);
      if (s.running) this.started.set(true);
      if (!this.started()) return;
      if (s.running) {
        this.sawRunning = true;
      } else if ((this.retryMode() ? this.retryExitObserved() : this.sawRunning) && s.exit_code === 0 && !s.cancel_requested) {
        this.dialogRef.close(true);
      }
    });
  }

  protected noteRetrySubmitted(): void {
    this.retryMode.set(true); this.acceptedRetryJob.set(null); this.started.set(true);
    // Keep sawRunning as a pending manual refresh for earlier partial work.
    // It must not authorize automatic completion of this new retry intent.
  }

  protected noteRetryAccepted(jobId: string): void {
    this.retryMode.set(true); this.acceptedRetryJob.set(jobId); this.started.set(true);
  }

  async ngOnInit(): Promise<void> {
    void this.scan.connect();
    try {
      this.directories.set(await this.scan.loadDirectories());
    } catch {
      this.dirLoadError.set(true);
    } finally {
      this.loadingDirs.set(false);
    }
  }

  async start(): Promise<void> {
    const dir = this.selectedDir();
    if (!dir || this.started() || !this.statusKnown() || this.observationError() || this.status().running) return;
    this.started.set(true);
    this.startRefusal.set(null);
    try {
      await this.scan.startScan([dir]);
    } catch (err) {
      if (err instanceof HttpErrorResponse && DEFINITE_REFUSALS.has(err.status)) {
        // The server answered and refused (a library job holds the lock, the
        // directory is not configured): no scan started, so give the button back.
        this.started.set(false);
        const detail = typeof err.error?.detail === 'string' ? err.error.detail : undefined;
        this.startRefusal.set(detail ? { detail } : { key: I18N.errors.action_failed });
        return;
      }
      // A lost start response is uncertain. Recover observation; never repeat
      // the POST automatically or turn its failure into another Start button.
      this.startError.set(true);
      await this.scan.connect();
    }
  }

  protected retryStatus(): void { void this.scan.connect(); }

  protected askStop(): void {
    if (this.canCancel()) this.pendingStopId.set(this.status().job_id!);
  }

  protected async confirmStop(): Promise<void> {
    const jobId = this.pendingStopId();
    if (!jobId || !this.canCancel() || this.status().job_id !== jobId || this.stopping()) {
      this.pendingStopId.set(null); return;
    }
    this.stopTargetId = jobId;
    this.stopping.set(true); this.stopError.set(false);
    try {
      await this.scan.cancelScan(jobId);
      this.pendingStopId.set(null);
    } catch {
      this.stopError.set(true);
      await this.scan.connect(); // Observe only; never repeat the stop POST automatically.
    } finally { this.stopping.set(false); }
  }
}
