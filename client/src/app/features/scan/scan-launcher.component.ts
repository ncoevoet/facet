import { ChangeDetectionStrategy, Component, OnInit, computed, effect, inject, signal } from '@angular/core';
import { MatDialogRef, MatDialogModule } from '@angular/material/dialog';
import { MatButtonModule } from '@angular/material/button';
import { MatIconModule } from '@angular/material/icon';
import { MatProgressBarModule } from '@angular/material/progress-bar';
import { ScanService, ScanDirectory } from '../../core/services/scan.service';
import { TranslatePipe } from '../../shared/pipes/translate.pipe';
import { I18N } from '../../core/i18n/keys';

/**
 * Superadmin-only dialog to pick a configured directory and launch + watch a
 * scoring scan in-app. Binds the live ScanService status (SSE with polling
 * fallback) to a progress bar and an output tail, and closes with `true` once
 * the scan finishes cleanly so the gallery can refresh.
 */
@Component({
  selector: 'app-scan-launcher',
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [MatDialogModule, MatButtonModule, MatIconModule, MatProgressBarModule, TranslatePipe],
  template: `
    <h2 mat-dialog-title>{{ I18N.scan.title | translate }}</h2>
    <mat-dialog-content class="!pt-2 min-w-[22rem] max-w-[34rem]">
      @if (!started()) {
        @if (loadingDirs()) {
          <p class="opacity-60 text-sm py-4">{{ I18N.scan.loading_directories | translate }}</p>
        } @else if (directories().length === 0) {
          <p class="opacity-60 text-sm py-4">{{ I18N.scan.no_directories | translate }}</p>
        } @else {
          <p class="text-sm opacity-70 mb-2">{{ I18N.scan.pick_directory | translate }}</p>
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
          <mat-icon class="!text-base !w-4 !h-4" [class.text-green-500]="connected()">
            {{ connected() ? 'cloud_done' : 'sync' }}
          </mat-icon>
          <span class="opacity-80">{{ phaseLabel() | translate }}</span>
          @if (eta() !== null) {
            <span class="opacity-50 ml-auto">{{ I18N.scan.eta | translate }} {{ eta() }}s</span>
          }
        </div>
        <mat-progress-bar [mode]="progressValue() === null ? 'indeterminate' : 'determinate'"
                          [value]="progressValue() ?? 0" />
        <pre class="mt-3 text-xs font-mono whitespace-pre-wrap max-h-48 overflow-y-auto opacity-70 bg-[var(--mat-sys-surface-container)] rounded p-2">{{ outputTail() }}</pre>
      }
    </mat-dialog-content>
    <mat-dialog-actions align="end">
      <button mat-button mat-dialog-close>{{ I18N.scan.close | translate }}</button>
      @if (!started()) {
        <button mat-flat-button color="primary"
                [disabled]="!selectedDir()"
                (click)="start()">
          {{ I18N.scan.start_button | translate }}
        </button>
      }
    </mat-dialog-actions>
  `,
})
export class ScanLauncherComponent implements OnInit {
  protected readonly I18N = I18N;
  private readonly scan = inject(ScanService);
  private readonly dialogRef = inject(MatDialogRef<ScanLauncherComponent>);

  protected readonly directories = signal<ScanDirectory[]>([]);
  protected readonly selectedDir = signal<string | null>(null);
  protected readonly loadingDirs = signal(true);
  protected readonly started = signal(false);

  protected readonly status = this.scan.status;
  protected readonly connected = this.scan.connected;
  // ScanService is a root singleton; its status can still hold a prior run's
  // {running:false, exit_code:0}. Only auto-close once THIS run was seen live.
  private sawRunning = false;

  protected readonly progressValue = computed(() => {
    const p = this.status().progress;
    if (!p || !p.total) return null;
    return Math.round(((p.current ?? 0) / p.total) * 100);
  });
  protected readonly phaseLabel = computed(() => this.status().progress?.phase ?? I18N.scan.running);
  protected readonly eta = computed(() => this.status().progress?.eta_seconds ?? null);
  protected readonly outputTail = computed(() => this.status().output.slice(-20).join('\n'));

  constructor() {
    // Close with success once THIS run was observed running and then finished
    // cleanly — guarding against a stale prior-run success in the shared signal.
    effect(() => {
      const s = this.status();
      if (!this.started()) return;
      if (s.running) {
        this.sawRunning = true;
      } else if (this.sawRunning && s.exit_code === 0) {
        this.dialogRef.close(true);
      }
    });
  }

  async ngOnInit(): Promise<void> {
    try {
      this.directories.set(await this.scan.loadDirectories());
    } finally {
      this.loadingDirs.set(false);
    }
  }

  async start(): Promise<void> {
    const dir = this.selectedDir();
    if (!dir) return;
    this.started.set(true);
    await this.scan.startScan([dir]);
  }
}
