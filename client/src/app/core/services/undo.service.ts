import { Injectable, inject } from '@angular/core';
import { MatSnackBar } from '@angular/material/snack-bar';
import { I18nService } from './i18n.service';
import { I18N } from '../i18n/keys';

export interface UndoableCommand {
  /** i18n key for the snackbar message. */
  labelKey: string;
  labelParams?: Record<string, string | number>;
  /**
   * Executes the action for deferred-commit commands (commit on snackbar
   * timeout). Invert-strategy commands already executed - pass undefined.
   */
  commit?: () => Promise<void>;
  /** Reverses the action (inverse API calls + local state restore). */
  undo: () => Promise<void>;
}

/**
 * Single-slot undo manager. Shows a snackbar with an Undo action for ~7s.
 *
 * Two strategies:
 * - invert: the action is already committed; Undo issues inverse calls.
 * - deferred commit: the action is only applied locally; the real API call
 *   fires when the snackbar times out (or the page hides), Undo cancels it.
 *
 * Registering a new command while a deferred one is pending commits the
 * pending one first, so at most one command is ever in flight.
 */
@Injectable({ providedIn: 'root' })
export class UndoService {
  private snackBar = inject(MatSnackBar);
  private i18n = inject(I18nService);

  private pendingCommit: (() => Promise<void>) | null = null;

  constructor() {
    // Deferred commits must not be lost when the tab closes mid-countdown
    window.addEventListener('pagehide', () => { void this.flushPending(); });
  }

  register(cmd: UndoableCommand): void {
    void this.flushPending();

    if (cmd.commit) {
      this.pendingCommit = cmd.commit;
    }

    const ref = this.snackBar.open(
      this.i18n.t(cmd.labelKey, cmd.labelParams),
      this.i18n.t(I18N.undo.action),
      { duration: 7000 },
    );

    let undone = false;
    ref.onAction().subscribe(() => {
      undone = true;
      if (this.pendingCommit === cmd.commit) this.pendingCommit = null;
      cmd.undo()
        .then(() => this.snackBar.open(this.i18n.t(I18N.undo.restored), '', { duration: 2000 }))
        .catch(() => this.snackBar.open(this.i18n.t(I18N.undo.restore_failed), '', { duration: 3000 }));
    });

    ref.afterDismissed().subscribe(() => {
      if (!undone && cmd.commit && this.pendingCommit === cmd.commit) {
        this.pendingCommit = null;
        void cmd.commit().catch(() => {
          this.snackBar.open(this.i18n.t(I18N.errors.action_failed), '', { duration: 3000 });
        });
      }
    });
  }

  /** Commit any pending deferred command immediately. */
  async flushPending(): Promise<void> {
    const commit = this.pendingCommit;
    this.pendingCommit = null;
    if (commit) {
      try {
        await commit();
      } catch { /* best effort - pagehide/preemption path */ }
    }
  }
}
