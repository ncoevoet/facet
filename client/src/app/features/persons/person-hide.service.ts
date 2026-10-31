import { Injectable, inject } from '@angular/core';
import { MatSnackBar } from '@angular/material/snack-bar';
import { firstValueFrom } from 'rxjs';
import { ApiService } from '../../core/services/api.service';
import { I18nService } from '../../core/services/i18n.service';
import { UserActivityJournal } from '../../core/agent/user-activity-journal.service';
import { UndoService } from '../../core/services/undo.service';
import { I18N } from '../../core/i18n/keys';

/** How long an Ignore can be undone. */
export const IGNORE_UNDO_MS = 10_000;

/**
 * Ignore (hide) or restore (unhide) a person: the API call, the activity journal,
 * and the user feedback, shared by the persons page and the person/face menu.
 * An Ignore offers Undo for ``IGNORE_UNDO_MS``; a restore says so. Each caller
 * keeps its own refresh: it runs on the returned promise's ``true`` and, for an
 * Undo, through ``onUndone`` once the person is visible again.
 */
@Injectable({ providedIn: 'root' })
export class PersonHideService {
  private readonly api = inject(ApiService);
  private readonly snackBar = inject(MatSnackBar);
  private readonly i18n = inject(I18nService);
  private readonly journal = inject(UserActivityJournal);
  private readonly undo = inject(UndoService);

  /** Resolves ``true`` once the change is stored, ``false`` after the error snackbar. */
  async setHidden(personId: number, hidden: boolean, onUndone: () => Promise<void>): Promise<boolean> {
    try {
      await firstValueFrom(this.api.post(`/persons/${personId}/${hidden ? 'hide' : 'unhide'}`));
    } catch {
      this.snackBar.open(this.i18n.t(I18N.persons.hide_error), '', { duration: 3000 });
      return false;
    }
    this.journal.record('person', [], { action: hidden ? 'hide' : 'unhide', person_id: personId });
    if (hidden) {
      this.undo.register({
        labelKey: I18N.persons.hidden_done,
        durationMs: IGNORE_UNDO_MS,
        undo: async () => {
          await firstValueFrom(this.api.post(`/persons/${personId}/unhide`));
          this.journal.record('person', [], { action: 'unhide', person_id: personId });
          await onUndone();
        },
      });
    } else {
      this.snackBar.open(this.i18n.t(I18N.persons.unhidden_done), '', { duration: 2000 });
    }
    return true;
  }
}
