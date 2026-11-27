import { ChangeDetectionStrategy, Component, DestroyRef, OnInit, computed, effect, inject, signal, untracked } from '@angular/core';
import { HttpErrorResponse } from '@angular/common/http';
import { MatDialogRef, MatDialogModule } from '@angular/material/dialog';
import { MatButtonModule } from '@angular/material/button';
import { MatIconModule } from '@angular/material/icon';
import { MatProgressBarModule } from '@angular/material/progress-bar';
import { RecentPhoto, ScanService, ScanDirectory } from '../../core/services/scan.service';
import { TranslatePipe } from '../../shared/pipes/translate.pipe';
import { FilenamePipe } from '../../shared/pipes/filename.pipe';
import { I18N, i18nKeys } from '../../core/i18n/keys';
import { ScanHistoryComponent } from './scan-history.component';
import { SHOWCASE_PHOTOS, ScanShowcaseComponent } from './scan-showcase.component';

/** Statuses that prove the server refused this start (a 409 may still mean another scan runs). */
const DEFINITE_REFUSALS = new Set([400, 403, 409, 422, 429]);

/** A busy library answers 503 before it spawns anything; any other 503 may be a proxy that lost the start. */
const isRefusal = (err: HttpErrorResponse): boolean =>
  DEFINITE_REFUSALS.has(err.status) || (err.status === 503 && err.error?.detail === 'library_busy');

const STAGES = ['find', 'analyze', 'organize'] as const;

const STAGE_OF_PHASE: Record<string, number> = {
  gather: 0, scoring: 1, bursts: 2, sequences: 2, tagging: 2, moments: 2, junk: 2, vec: 2, done: 3,
};

/** What a model is doing for the photo, in the user's terms; first match wins. */
const ANALYSIS_OF_MODEL: readonly (readonly [RegExp, keyof typeof I18N.scan.analyze])[] = [
  [/saliency/, 'subject'],
  [/samp_net|composition/, 'composition'],
  // Quality before faces: topiq_nr_face rates the faces it is given, it does not find them.
  [/topiq|liqe|hyperiqa|dbcnn|musiq|clipiqa|qrealign|aesthetic|deqa/, 'quality'],
  [/face/, 'faces'],
  [/clip|tagger|qwen|vlm/, 'content'],
];

/**
 * Superadmin-only dialog to pick a configured directory and launch + watch a
 * scoring scan in-app. Binds the live ScanService status (SSE with polling
 * fallback) to a progress bar and an output tail, and closes with `true` once
 * the scan finishes cleanly so the gallery can refresh.
 */
@Component({
  selector: 'app-scan-launcher',
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [MatDialogModule, MatButtonModule, MatIconModule, MatProgressBarModule, TranslatePipe, FilenamePipe, ScanHistoryComponent, ScanShowcaseComponent],
  template: `
    <h2 mat-dialog-title>{{ I18N.scan.title | translate }}</h2>
    <mat-dialog-content class="!pt-2 min-w-0 w-full max-w-[34rem]">
      @if (observationError()) {
        <p role="alert" class="text-sm">{{ I18N.scan.status_unavailable | translate }}</p>
        <button mat-stroked-button (click)="retryStatus()">{{ I18N.scan.retry_status | translate }}</button>
      } @else if (!statusKnown() && !started()) {
        <!-- Once a scan is started the progress header says this in its own status region. -->
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
              <label class="flex items-center gap-3 px-2 py-2 rounded cursor-pointer hover:bg-[var(--mat-sys-surface-container-high)]">
                <input type="radio" name="scanDir" class="shrink-0 w-4 h-4 accent-[var(--mat-sys-primary)]" [value]="dir.path"
                       [checked]="selectedDir() === dir.path"
                       (change)="selectedDir.set(dir.path)" />
                <mat-icon class="shrink-0 text-[var(--mat-sys-primary)]" aria-hidden="true">folder</mat-icon>
                <span class="min-w-0 flex flex-col">
                  <span class="text-sm font-medium truncate">{{ (dir.path | filename) || dir.path }}</span>
                  <span class="text-xs text-[var(--mat-sys-on-surface-variant)] truncate" [title]="dir.path">{{ dir.path }}</span>
                </span>
              </label>
            }
          </div>
        }
      } @else {
        <!-- Hidden while the log is read: both together are taller than the dialog. -->
        @if (live() && status().kind === 'scan' && !readingLog()) {
          <app-scan-showcase class="mb-4" [photos]="recent()" />
        }
        @if (stages(); as stageList) {
          <ol class="flex items-center gap-2 mb-4 mt-1 p-0 list-none text-xs" [attr.aria-label]="I18N.scan.stages_label | translate">
            @for (stage of stageList; track stage.key) {
              <li class="flex items-center gap-1.5" [attr.aria-current]="stage.state === 'current' ? 'step' : null"
                  [class.text-[var(--mat-sys-on-surface-variant)]]="stage.state === 'pending'"
                  [class.font-medium]="stage.state === 'current'">
                <span class="grid place-items-center w-5 h-5 rounded-full text-[11px] tabular-nums"
                      [class.bg-[var(--mat-sys-primary)]]="stage.state !== 'pending'"
                      [class.text-[var(--mat-sys-on-primary)]]="stage.state !== 'pending'"
                      [class.border]="stage.state === 'pending'"
                      [class.border-[var(--mat-sys-outline)]]="stage.state === 'pending'">
                  @if (stage.state === 'done') { <mat-icon class="!text-sm !w-3.5 !h-3.5 !leading-none" aria-hidden="true">check</mat-icon> }
                  @else { {{ $index + 1 }} }
                </span>
                <span>{{ stage.label | translate }}</span>
              </li>
              @if (!$last) {
                <li aria-hidden="true" class="flex-1 h-px"
                    [class.bg-[var(--mat-sys-primary)]]="stage.state === 'done'"
                    [class.bg-[var(--mat-sys-outline-variant)]]="stage.state !== 'done'"></li>
              }
            }
          </ol>
        }
        <div class="flex items-baseline gap-3">
          <span role="status" class="text-base font-medium">
            @if (phaseLabelKey(); as key) { {{ key | translate }} }
            @else { {{ status().progress?.phase }} }
          </span>
          @if (photoCount(); as count) {
            <span class="ml-auto text-sm tabular-nums text-[var(--mat-sys-on-surface-variant)]">{{ I18N.scan.count | translate:count }}</span>
          } @else if (photoTotal(); as total) {
            <span class="ml-auto text-sm tabular-nums text-[var(--mat-sys-on-surface-variant)]">{{ (total === 1 ? I18N.scan.total : I18N.scan.total_plural) | translate:{ total } }}</span>
          }
        </div>
        <div class="flex items-baseline gap-3 min-h-5 mb-2 text-sm text-[var(--mat-sys-on-surface-variant)]">
          @if (stepLabelKey(); as key) { <span>{{ key | translate }}…</span> }
          @if (timeLeft(); as left) {
            <span class="ml-auto tabular-nums">{{ left.key | translate:left.vars }}</span>
          }
        </div>
        @if (statusKnown() && status().running && !observationError()) {
          <mat-progress-bar class="!h-1.5 rounded-full" [mode]="progressValue() === null ? 'indeterminate' : 'determinate'"
                            [value]="progressValue() ?? 0" [attr.aria-label]="I18N.scan.progress_label | translate" />
        }
        @if (outputTail()) {
          <!-- A reversed box opens at its oldest line; 0 is its newest. -->
          <details #log class="mt-3" [open]="logOpen()" (toggle)="readingLog.set(log.open); logBox.scrollTop = 0">
            <summary class="min-h-11 cursor-pointer select-none text-sm font-medium">
              {{ ((!statusKnown() || observationError()) ? I18N.scan.last_observed_output : I18N.scan.details) | translate }}
            </summary>
            <!-- column-reverse keeps the newest line in view as lines arrive -->
            <div #logBox class="max-h-48 overflow-y-auto flex flex-col-reverse rounded bg-[var(--mat-sys-surface-container)]">
              <pre class="m-0 p-2 text-xs font-mono whitespace-pre-wrap [overflow-wrap:anywhere] opacity-70">{{ outputTail() }}</pre>
            </div>
          </details>
        }
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
      <!-- Closing never stops a scan; while one runs the button says so. -->
      <button mat-button [mat-dialog-close]="(sawRunning || retryExitObserved()) && statusKnown() && !observationError() && !status().running && status().exit_code !== null">{{ (live() ? I18N.scan.run_in_background : I18N.scan.close) | translate }}</button>
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

  /** The newest photos this scan added to the library, refreshed each time it saves a chunk. */
  protected readonly recent = signal<readonly RecentPhoto[]>([]);
  protected readonly readingLog = signal(false);
  private recentInFlight = false;
  private recentPending = false;
  private destroyed = false;
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
    if (!p) return null;
    // `fraction` moves within a chunk; `current` only once a whole chunk is saved.
    if (typeof p.fraction === 'number') return Math.round(Math.min(1, Math.max(0, p.fraction)) * 100);
    if (!p.total) return null;
    return Math.round(((p.current ?? 0) / p.total) * 100);
  });
  protected readonly live = computed(() => this.statusKnown() && !this.observationError() && this.status().running && !this.status().cancel_requested);
  /** The three things a scan does, for a scan's own phases only (a recompute has no such shape). */
  protected readonly stages = computed(() => {
    const phase = this.status().progress?.phase;
    if (!this.live() || !phase || !Object.hasOwn(STAGE_OF_PHASE, phase)) return null;
    const at = STAGE_OF_PHASE[phase];
    return STAGES.map((key, i) => ({ key, label: I18N.scan.stage[key], state: i < at ? 'done' : i === at ? 'current' : 'pending' }));
  });
  protected readonly photoCount = computed(() => {
    const p = this.status().progress;
    // Photos only count once their chunk is saved: a small scan sits in its first
    // chunk throughout, so "0 of N" would contradict the moving bar.
    if (!this.live() || p?.phase !== 'scoring' || !p.total || !p.current) return null;
    return { current: p.current ?? 0, total: p.total };
  });
  /** Before the first chunk is saved, the size of the job is still worth saying. */
  protected readonly photoTotal = computed(() => {
    const p = this.status().progress;
    return this.live() && p?.phase === 'scoring' && p.total ? p.total : null;
  });
  protected readonly stepLabelKey = computed(() => {
    const p = this.status().progress;
    if (!this.live() || !p?.step || !Object.hasOwn(I18N.scan.step, p.step)) return null;
    if (p.step === 'analyze' && p.detail) {
      const kind = ANALYSIS_OF_MODEL.find(([pattern]) => pattern.test(p.detail!))?.[1];
      if (kind) return I18N.scan.analyze[kind];
    }
    return (I18N.scan.step as Record<string, string>)[p.step];
  });
  protected readonly timeLeft = computed(() => {
    const seconds = this.eta();
    if (seconds === null) return null;
    return seconds < 60
      ? { key: I18N.scan.time_left_seconds, vars: { n: Math.max(1, Math.round(seconds)) } }
      : { key: I18N.scan.time_left_minutes, vars: { n: Math.ceil(seconds / 60) } };
  });
  /** The raw log stays folded away while things go well, and opens itself when they do not. */
  protected readonly logOpen = computed(() => !this.statusKnown() || this.observationError()
    || (!this.status().running && this.status().exit_code !== null && this.status().exit_code !== 0));
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
  // Libraries pad their output with blank lines; they only push the real lines out of view.
  protected readonly outputTail = computed(() => this.status().output.filter(line => line.trim()).slice(-20).join('\n'));

  /** Photos this scan has saved so far; each new chunk brings new photos to show. */
  private readonly savedSoFar = computed(() => {
    const p = this.status().progress;
    return this.live() && this.status().kind === 'scan' && p?.phase === 'scoring' ? p.current ?? 0 : 0;
  });

  constructor() {
    inject(DestroyRef).onDestroy(() => { this.destroyed = true; });
    effect(() => {
      if (this.savedSoFar() > 0) untracked(() => void this.loadRecent());
    });
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

  /** Single-flight: ticks that arrive mid-request collapse into one follow-up read. */
  private async loadRecent(): Promise<void> {
    if (this.recentInFlight) { this.recentPending = true; return; }
    const since = this.status().started_at;
    if (since == null) return;
    this.recentInFlight = true;
    try {
      this.recent.set(await this.scan.loadRecentPhotos(SHOWCASE_PHOTOS, since));
    } catch { /* Decorative: the scan's own status is unaffected. */ }
    this.recentInFlight = false;
    if (this.recentPending && !this.destroyed) { this.recentPending = false; void this.loadRecent(); }
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
      const directories = await this.scan.loadDirectories();
      this.directories.set(directories);
      if (directories.length === 1) this.selectedDir.set(directories[0].path);
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
      if (err instanceof HttpErrorResponse && isRefusal(err)) {
        // The server answered and refused (a library job holds the lock, the
        // directory is not configured): this start did not happen, so give the
        // button back, and re-read status so a scan started elsewhere shows.
        this.started.set(false);
        const detail = typeof err.error?.detail === 'string' ? err.error.detail : undefined;
        this.startRefusal.set(detail ? { detail } : { key: I18N.errors.action_failed });
        void this.scan.connect();
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
