import { DestroyRef, Injectable, inject } from '@angular/core';
import { MatSnackBar, MatSnackBarRef, TextOnlySnackBar } from '@angular/material/snack-bar';
import { I18nService } from './i18n.service';
import { I18N } from '../i18n/keys';
import { isImeOrRepeat, isShortcutContextBlocked, isUndoChord } from '../../shared/utils/keyboard';

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
  /** How long the Undo stays offered; 7 s unless the action asks for longer. */
  durationMs?: number;
}

/**
 * Single-slot undo manager. Shows a snackbar with an Undo action for ~7s, or
 * the command's own ``durationMs``.
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
  /** The Undo snackbar on screen, or null once it is dismissed or replaced. */
  private showing: MatSnackBarRef<TextOnlySnackBar> | null = null;

  constructor() {
    // Deferred commits must not be lost when the tab closes mid-countdown
    window.addEventListener('pagehide', () => { void this.flushPending(); });
    // Capture phase, so Ctrl/Cmd+Z works on every page, including regions
    // such as the darkroom that stop keys from bubbling to the document.
    const onKey = (event: KeyboardEvent) => this.onUndoKey(event);
    document.addEventListener('keydown', onKey, true);
    inject(DestroyRef).onDestroy(() => document.removeEventListener('keydown', onKey, true));
  }

  /** Ctrl/Cmd+Z presses the snackbar's Undo while one is showing. A text field
   *  keeps its own undo, and an open dialog or bottom sheet keeps the key. */
  private onUndoKey(event: KeyboardEvent): void {
    if (!isUndoChord(event) || isImeOrRepeat(event) || isShortcutContextBlocked(event)) return;
    if (this.undoShowing()) event.preventDefault();
  }

  /** Presses Undo on the snackbar on screen. False when none is showing. */
  undoShowing(): boolean {
    const ref = this.showing;
    if (!ref) return false;
    ref.dismissWithAction();
    return true;
  }

  register(cmd: UndoableCommand): void {
    void this.flushPending();

    if (cmd.commit) {
      this.pendingCommit = cmd.commit;
    }

    const ref = this.snackBar.open(
      this.i18n.t(cmd.labelKey, cmd.labelParams),
      this.i18n.t(I18N.undo.action),
      { duration: cmd.durationMs ?? 7000 },
    );
    this.showing = ref;

    let undone = false;
    ref.onAction().subscribe(() => {
      undone = true;
      if (this.pendingCommit === cmd.commit) this.pendingCommit = null;
      cmd.undo()
        .then(() => this.snackBar.open(this.i18n.t(I18N.undo.restored), '', { duration: 2000 }))
        .catch(() => this.snackBar.open(this.i18n.t(I18N.undo.restore_failed), '', { duration: 3000 }));
    });

    ref.afterDismissed().subscribe(() => {
      if (this.showing === ref) this.showing = null;
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
