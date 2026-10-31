import { Injectable, inject } from '@angular/core';
import { Observable, firstValueFrom } from 'rxjs';
import { UserActivityJournal } from '../../core/agent/user-activity-journal.service';
import { PhotoStackService, StackMutation, StackRegroupMutation } from '../../core/services/photo-stack.service';
import { UndoService } from '../../core/services/undo.service';
import { I18N } from '../../core/i18n/keys';
import { GalleryStore } from './gallery.store';

export interface StackCommit {
  /** Every photo the mutation touches, for the activity journal. */
  paths: string[];
  action: 'create' | 'update' | 'unstack';
  labelKey: string;
  labelParams?: Record<string, string | number>;
  /** Root-owned epoch from `PhotoStackService.context()`; it outlives the caller and gates Undo. */
  session: () => boolean;
  /** Narrower liveness of the caller (an open dialog) checked once the request returns; defaults to `session`. */
  live?: () => boolean;
  /** Runs only after a successful revert. */
  onUndone?: () => void;
}

/** The one place a stack write is journaled, refreshed and offered an Undo. */
@Injectable({ providedIn: 'root' })
export class StackActionsService {
  private readonly stacks = inject(PhotoStackService);
  private readonly journal = inject(UserActivityJournal);
  private readonly store = inject(GalleryStore);
  private readonly undo = inject(UndoService);

  /**
   * Rejects when the server refuses. Resolves false, without journaling or refreshing,
   * when the caller or the account lapsed while the request was in flight.
   */
  async commit(request: Observable<StackMutation | StackRegroupMutation>, commit: StackCommit): Promise<boolean> {
    const result = await firstValueFrom(request);
    if (!this.stacks.isLive(commit.live ?? commit.session)) return false;
    if ('changed' in result && !result.changed) return true;
    const paths = 'affected_paths' in result ? result.affected_paths : commit.paths;
    this.journal.record('stack', paths, commit.action);
    void this.store.refreshPaths(null);
    const entryId = result.undo?.entry_id;
    if (entryId !== undefined) {
      this.undo.register({
        labelKey: commit.labelKey, labelParams: commit.labelParams,
        // A snackbar outlives the page and the account that made the stack.
        undo: async () => {
          this.stacks.assertLive(commit.session);
          await firstValueFrom(this.stacks.revert(entryId));
          this.stacks.assertLive(commit.session);
          this.journal.record('stack', paths, 'undo');
          await this.store.refreshPaths(null);
          commit.onUndone?.();
        },
      });
    }
    return true;
  }

  /** One-step stacking outside the stack editor. `onUndone` runs only after a successful revert. */
  async create(paths: string[], cover: string, onUndone?: () => void): Promise<void> {
    await this.commit(this.stacks.create(paths, cover), {
      paths, action: 'create', session: this.stacks.context(), onUndone,
      labelKey: I18N.stacks.stacked, labelParams: { count: paths.length },
    });
  }
}
