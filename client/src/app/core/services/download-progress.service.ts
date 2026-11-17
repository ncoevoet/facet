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
/** A lost connection (0) or session (401, 403) fails every later file too. */
const HALT_STATUSES = new Set([0, 401, 403]);
/** Failures in a row that stop the batch: a revoked shared link answers 404, a down server 5xx. */
const MAX_CONSECUTIVE_FAILURES = 3;

/**
 * Downloads a batch of files one after another behind a persistent progress
 * snackbar with Cancel, then one toast that says how the batch ended. A failed
 * file is counted and skipped rather than aborting the rest, until the failures
 * show the rest cannot succeed either.
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
    let finished = false;
    const state: DownloadProgressState = {
      done: done.asReadonly(),
      failed: failed.asReadonly(),
      total: items.length,
      cancel: () => { stopped = true; cancelled.next(); },
    };
    // A failed render must not raise the global 5xx toast: the snackbar shows
    // one message at a time, so it would replace the progress notification.
    const context = new HttpContext().set(HANDLE_SERVER_ERROR_LOCALLY, true);
    let progress: MatSnackBarRef<DownloadProgressSnackComponent> | undefined;
    // Never open over another snackbar (an Undo offer, say): opening would
    // dismiss it. Show the progress once that one has gone, and bring it back
    // the same way whenever another snackbar replaces it.
    const showProgress = () => {
      if (finished) return;
      progress = this.snackBar.openFromComponent(DownloadProgressSnackComponent, { data: state });
      progress.afterDismissed().subscribe(() => {
        if (!finished) this.whenNoOtherSnackbar(showProgress);
      });
    };
    this.whenNoOtherSnackbar(showProgress);
    let streak = 0;
    try {
      for (const item of items) {
        if (stopped || !current()) break;
        try {
          const blob = await firstValueFrom(this.api.getRaw(item.url, context).pipe(takeUntil(cancelled)), { defaultValue: null });
          if (blob === null || !current()) break;
          downloadBlob(blob, item.filename);
          streak = 0;
        } catch (ex) {
          failed.update(n => n + 1);
          streak++;
          // One logout or access toast from the interceptor, not one failed
          // request per remaining photo.
          stopped ||= (ex instanceof HttpErrorResponse && HALT_STATUSES.has(ex.status)) || streak >= MAX_CONSECUTIVE_FAILURES;
        }
        done.update(n => n + 1);
        if (stopped) break;
      }
    } finally {
      finished = true;
      progress?.dismiss();
      cancelled.complete();
    }
    if (!current()) return;
    const message = this.resultMessage(done() - failed(), failed(), items.length, stopped);
    // The result replaces the progress notification, but waits for any other
    // snackbar still showing: opening over an Undo offer would dismiss it.
    this.whenNoOtherSnackbar(() => {
      if (current()) this.snackBar.open(message, '', { duration: RESULT_TOAST_MS });
    }, progress);
  }

  private resultMessage(saved: number, failed: number, total: number, stopped: boolean): string {
    const keys = I18N.gallery.selection;
    if (stopped) return this.i18n.t(keys.download_cancelled, { saved, total });
    if (failed) return this.i18n.t(keys.download_partial, { saved, total, failed });
    if (total === 1) return this.i18n.t(keys.download_done_one);
    return this.i18n.t(keys.download_done, { count: saved });
  }

  /**
   * Runs `show` once no snackbar but `own` is on screen. `_openedSnackBarRef` is
   * Material's only handle on the snackbar showing at any level, opened by any
   * caller; it is underscore-named, so the spec pins it against the real service.
   */
  private whenNoOtherSnackbar(show: () => void, own?: MatSnackBarRef<unknown>): void {
    const other = this.snackBar._openedSnackBarRef;
    if (!other || other === own) {
      show();
      return;
    }
    other.afterDismissed().subscribe(() => this.whenNoOtherSnackbar(show, own));
  }
}
