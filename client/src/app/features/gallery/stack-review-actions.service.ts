import { Injectable, inject } from '@angular/core';
import { firstValueFrom } from 'rxjs';
import { components } from '../../core/api/schema';
import { ApiService } from '../../core/services/api.service';
import { PhotoStackService } from '../../core/services/photo-stack.service';
import { UndoService } from '../../core/services/undo.service';
import { UserActivityJournal } from '../../core/agent/user-activity-journal.service';
import { I18N } from '../../core/i18n/keys';
import { Photo } from '../../shared/models/photo.model';
import { GalleryStore } from './gallery.store';

export interface StackReviewCommand {
  session: () => boolean;
  live: () => boolean;
  /** Accepted exclusion returns a narrow draft inverse, independent of later edits. */
  exclude: () => () => void;
  /** Locks the still-open draft during Undo; a closed draft needs no local lock. */
  beginUndo: () => boolean;
  endUndo: () => void;
}

/** Explicit manual review, separate from the culling workflow and stack organization. */
@Injectable({ providedIn: 'root' })
export class StackReviewActionsService {
  private readonly api = inject(ApiService);
  private readonly stacks = inject(PhotoStackService);
  private readonly undo = inject(UndoService);
  private readonly journal = inject(UserActivityJournal);
  private readonly gallery = inject(GalleryStore);

  async reject(path: string, command: StackReviewCommand): Promise<boolean> {
    const current = () => this.stacks.isLive(command.session) && command.live();
    if (!current()) return false;
    const photo = await firstValueFrom(this.api.get<Photo>('/photo', { path }));
    if (!current() || photo.path !== path) return false;
    let receipt: number | undefined;
    if (!photo.is_rejected) {
      const result = await firstValueFrom(this.api.post<components['schemas']['BatchReviewResponse']>(
        '/photos/batch_review', { photo_paths: [path], decision: 'rejected' }));
      if (!current()) return false;
      if (result.count !== 1) throw new Error('Photo is no longer writable');
      receipt = result.undo_entry_id ?? undefined;
      if (receipt !== undefined) this.journal.record('reject', [path], true);
    }
    if (!current()) return false;
    const restore = command.exclude();
    void this.gallery.refreshPaths([path]);
    this.undo.register({
      labelKey: I18N.stacks.reject_excluded,
      undo: async () => {
        this.stacks.assertLive(command.session);
        if (!command.beginUndo()) throw new Error('Stack draft is busy');
        try {
          if (receipt !== undefined) {
            await firstValueFrom(this.api.post(`/organization_history/${receipt}/revert`, {}));
            this.stacks.assertLive(command.session);
            this.journal.record('reject', [path], false);
            void this.gallery.refreshPaths([path]);
          }
          restore();
        } finally { command.endUndo(); }
      },
    });
    return true;
  }
}
