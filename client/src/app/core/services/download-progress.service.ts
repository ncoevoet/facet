import { Injectable, Signal, inject, signal } from '@angular/core';
import { HttpContext, HttpErrorResponse } from '@angular/common/http';
import { MatSnackBar, MatSnackBarRef } from '@angular/material/snack-bar';
import { Subject, firstValueFrom, takeUntil } from 'rxjs';
import { ApiService } from './api.service';
import { I18nService } from './i18n.service';
import { I18N } from '../i18n/keys';
import { HANDLE_SERVER_ERROR_LOCALLY } from '../utils/http-error-context';
import { downloadBlob } from '../../shared/utils/download';
import { DownloadProgressSnackComponent } from '../../shared/components/download-progress-snack/download-progress-snack.component';

export interface DownloadItem {
  url: string;
  filename: string;
}

/** What the progress snackbar reads: photos processed so far, how many failed, and how to stop. */
export interface DownloadProgressState {
  readonly done: Signal<number>;
  readonly failed: Signal<number>;
  readonly total: number;
  cancel(): void;
}

const RESULT_TOAST_MS = 5000;
const AUTH_REFUSALS = new Set([401, 403]);

/**
 * Downloads a batch of files one after another behind a persistent progress
 * snackbar with Cancel, then one toast that says how the batch ended. A failed
 * file is counted and skipped rather than aborting the rest.
 */
@Injectable({ providedIn: 'root' })
export class DownloadProgressService {
  private readonly api = inject(ApiService);
  private readonly snackBar = inject(MatSnackBar);
  private readonly i18n = inject(I18nService);

  /** `current` going false (the page or link changed) stops the batch without a result toast. */
  async run(items: DownloadItem[], current: () => boolean = () => true): Promise<void> {
    if (!items.length) return;
    const done = signal(0);
    const failed = signal(0);
    const cancelled = new Subject<void>();
    let stopped = false;
    const state: DownloadProgressState = {
      done: done.asReadonly(),
      failed: failed.asReadonly(),
      total: items.length,
      cancel: () => { stopped = true; cancelled.next(); },
    };
    // A failed render must not raise the global 5xx toast: the snackbar shows
    // one message at a time, so it would replace the progress notification.
    const context = new HttpContext().set(HANDLE_SERVER_ERROR_LOCALLY, true);
    let shown = this.openProgress(state);
    try {
      for (const item of items) {
        if (stopped || !current()) break;
        // Another snackbar (an Undo offer, say) replaced the progress one: bring it
        // back once that one has gone, never over it.
        if (!shown.visible && !this.snackBar._openedSnackBarRef) shown = this.openProgress(state);
        let refused = false;
        try {
          const blob = await firstValueFrom(this.api.getRaw(item.url, context).pipe(takeUntil(cancelled)), { defaultValue: null });
          if (blob === null || !current()) break;
          downloadBlob(blob, item.filename);
        } catch (ex) {
          failed.update(n => n + 1);
          // A refused session refuses every later file too: one logout or
          // access toast from the interceptor, not one per remaining photo.
          refused = ex instanceof HttpErrorResponse && AUTH_REFUSALS.has(ex.status);
        }
        done.update(n => n + 1);
        if (refused) break;
      }
    } finally {
      shown.ref.dismiss();
      cancelled.complete();
    }
    if (!current()) return;
    const message = this.resultMessage(done() - failed(), failed(), items.length, stopped);
    this.snackBar.open(message, '', { duration: RESULT_TOAST_MS });
  }

  private resultMessage(saved: number, failed: number, total: number, stopped: boolean): string {
    const keys = I18N.gallery.selection;
    if (stopped) return this.i18n.t(keys.download_cancelled, { saved, total });
    if (failed) return this.i18n.t(keys.download_partial, { saved, total, failed });
    if (total === 1) return this.i18n.t(keys.download_done_one);
    return this.i18n.t(keys.download_done, { count: saved });
  }

  private openProgress(state: DownloadProgressState): { ref: MatSnackBarRef<DownloadProgressSnackComponent>; visible: boolean } {
    const ref = this.snackBar.openFromComponent(DownloadProgressSnackComponent, { data: state });
    const shown = { ref, visible: true };
    ref.afterDismissed().subscribe(() => { shown.visible = false; });
    return shown;
  }
}
