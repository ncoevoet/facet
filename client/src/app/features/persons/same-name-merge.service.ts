import { Component, Injectable, inject, signal, computed, ChangeDetectionStrategy } from '@angular/core';
import { MatButtonModule } from '@angular/material/button';
import { MatIconModule } from '@angular/material/icon';
import { MatDialog, MatDialogModule, MAT_DIALOG_DATA, MatDialogRef } from '@angular/material/dialog';
import { MatSnackBar } from '@angular/material/snack-bar';
import { MatTooltipModule } from '@angular/material/tooltip';
import { firstValueFrom } from 'rxjs';
import { ApiService } from '../../core/services/api.service';
import { I18nService } from '../../core/services/i18n.service';
import { TranslatePipe } from '../../shared/pipes/translate.pipe';
import { PersonThumbnailUrlPipe } from '../../shared/pipes/thumbnail-url.pipe';
import { I18N, i18nKeys } from '../../core/i18n/keys';
import type { components } from '../../core/api/schema';
import { PersonFaceBoxesService } from '../../shared/components/photo-card/person-face-boxes.service';

/** Another person whose name matches a rename, ignoring case (``POST /api/persons/{id}/rename``). */
export type SameNamePerson = components['schemas']['SameNamePerson'];

/** ``POST /api/persons/{id}/rename``: ``RenamePersonResponse``. */
export type RenamePersonResponse = components['schemas']['RenamePersonResponse'];

/** A person in the same-name merge: the cluster being named, or one of its namesakes. */
export interface SameNameMergeCandidate {
  id: number;
  name: string;
  face_count: number;
}

export interface SameNameMergeDialogData {
  name: string;
  /** The cluster just named. */
  current: SameNameMergeCandidate;
  /** The other persons already carrying the name. */
  persons: SameNamePerson[];
}

/** The candidate that survives a merge of ``group``: the most faces, the first on a tie. */
export function mergeTarget<T extends { face_count: number }>(group: readonly T[]): T | null {
  return group.length === 0 ? null : group.reduce((best, p) => (p.face_count > best.face_count ? p : best));
}

/** One pair of ``POST /api/persons/merge_batch``. */
export interface PersonMerge {
  source_id: number;
  target_id: number;
}

export type SameNameMergeResult =
  | { status: 'declined' }
  | { status: 'merged'; targetId: number; merges: PersonMerge[] }
  | { status: 'failed' };

/**
 * A tile per person involved, the cluster being named first, each with its face
 * thumbnail, name and face count. Tiles are toggle buttons (all selected at first);
 * the selected tile that will survive the merge is marked as kept. Closes with the
 * selected ids (two or more), or ``null`` when cancelled.
 */
@Component({
  selector: 'app-same-name-merge-dialog',
  imports: [MatButtonModule, MatDialogModule, MatIconModule, MatTooltipModule, TranslatePipe, PersonThumbnailUrlPipe],
  changeDetection: ChangeDetectionStrategy.Eager,
  template: `
    <h2 mat-dialog-title class="truncate" [matTooltip]="I18N.persons.same_name_title | translate">
      {{ I18N.persons.same_name_title | translate }}
    </h2>
    <mat-dialog-content class="!flex !flex-col gap-3">
      <p>{{ I18N.persons.same_name_message | translate:{ count: data.persons.length, name: data.name } }}</p>
      <div class="grid grid-cols-2 sm:grid-cols-3 gap-3">
        @for (tile of tiles(); track tile.id) {
          <button
            type="button"
            class="relative flex flex-col items-center gap-1 p-3 rounded-lg border-2 transition-colors cursor-pointer text-center focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--mat-sys-primary)]"
            [class.border-[var(--mat-sys-primary)]]="tile.selected"
            [class.bg-[var(--mat-sys-primary-container)]]="tile.selected"
            [class.border-[var(--mat-sys-outline-variant)]]="!tile.selected"
            [class.opacity-60]="!tile.selected"
            [attr.aria-pressed]="tile.selected"
            (click)="toggle(tile.id)">
            @if (tile.selected) {
              <span class="absolute top-1.5 right-1.5 w-5 h-5 rounded-full bg-[var(--mat-sys-primary)] text-[var(--mat-sys-on-primary)] flex items-center justify-center" aria-hidden="true">
                <mat-icon class="!text-sm !w-4 !h-4 !leading-4">check</mat-icon>
              </span>
            }
            <img [src]="tile.id | personThumbnailUrl" alt="" class="w-16 h-16 rounded-full object-cover bg-[var(--mat-sys-surface-container-high)]" />
            <span class="text-sm font-medium truncate w-full">{{ tile.name }}</span>
            <span class="text-xs opacity-70">
              {{ (tile.face_count === 1 ? I18N.person_selector.face_count_one : I18N.person_selector.face_count) | translate:{ count: tile.face_count } }}
            </span>
            @if (tile.current) {
              <span class="text-xs opacity-70">{{ I18N.persons.same_name_this_group | translate }}</span>
            }
            @if (tile.kept) {
              <span class="mt-1 px-2 py-0.5 rounded-full text-xs font-semibold bg-[var(--mat-sys-primary)] text-[var(--mat-sys-on-primary)]">
                {{ I18N.persons.same_name_kept | translate }}
              </span>
            }
          </button>
        }
      </div>
    </mat-dialog-content>
    <mat-dialog-actions align="end">
      <button mat-button (click)="dialogRef.close(null)">{{ I18N.dialog.cancel | translate }}</button>
      <button mat-flat-button color="warn" [disabled]="selected().size < 2" (click)="confirm()">
        {{ I18N.persons.same_name_merge | translate }}
      </button>
    </mat-dialog-actions>
  `,
})
export class SameNameMergeDialogComponent {
  protected readonly I18N = i18nKeys();
  readonly data: SameNameMergeDialogData = inject(MAT_DIALOG_DATA);
  readonly dialogRef = inject(MatDialogRef<SameNameMergeDialogComponent, number[] | null>);
  private readonly candidates: SameNameMergeCandidate[] = [this.data.current, ...this.data.persons];
  readonly selected = signal(new Set(this.candidates.map((p) => p.id)));
  readonly tiles = computed(() => {
    const selected = this.selected();
    const kept = selected.size >= 2 ? mergeTarget(this.candidates.filter((p) => selected.has(p.id)))?.id : null;
    return this.candidates.map((p) => ({
      ...p,
      selected: selected.has(p.id),
      current: p.id === this.data.current.id,
      kept: p.id === kept,
    }));
  });

  toggle(id: number): void {
    this.selected.update((set) => {
      const next = new Set(set);
      if (next.has(id)) {
        next.delete(id);
      } else {
        next.add(id);
      }
      return next;
    });
  }

  confirm(): void {
    const ids = this.candidates.map((p) => p.id).filter((id) => this.selected().has(id));
    if (ids.length >= 2) this.dialogRef.close(ids);
  }
}

/**
 * The same-name merge offered after a rename, shared by the persons page and the
 * gallery's naming bar. Naming a cluster after a person who already has one usually
 * means clustering split that person: the user picks, on a tile per person, which
 * are the same person, and those fold into the largest of them, which keeps its
 * own spelling of the name. Unpicked persons stay apart, since two people may
 * share a name.
 *
 * The confirm says a merge cannot be undone, which is true: ``merge_batch`` deletes
 * the folded persons and records nothing in the organization history, whose
 * entries cover only GPS, dates, review flags and stacks.
 */
@Injectable({ providedIn: 'root' })
export class SameNameMergeService {
  private readonly api = inject(ApiService);
  private readonly dialog = inject(MatDialog);
  private readonly snackBar = inject(MatSnackBar);
  private readonly i18n = inject(I18nService);
  private readonly faceBoxes = inject(PersonFaceBoxesService);

  /** Ask which namesakes to fold in with ``person`` and merge them. ``sameName`` must not be empty. */
  async offer(
    person: { id: number; face_count: number },
    name: string,
    sameName: SameNamePerson[],
  ): Promise<SameNameMergeResult> {
    const ref = this.dialog.open(SameNameMergeDialogComponent, {
      data: {
        name,
        current: { id: person.id, name, face_count: person.face_count },
        persons: sameName,
      } as SameNameMergeDialogData,
      width: '95vw',
      maxWidth: '560px',
    });
    const picked = await firstValueFrom(ref.afterClosed());
    if (!Array.isArray(picked) || picked.length < 2) return { status: 'declined' };

    const chosen = new Set<number>(picked);
    const group = [person, ...sameName].filter((p) => chosen.has(p.id));
    const target = mergeTarget(group) as { id: number };
    const merges = group.filter((p) => p.id !== target.id).map((p) => ({ source_id: p.id, target_id: target.id }));
    try {
      await firstValueFrom(this.api.post('/persons/merge_batch', { merges }));
      this.faceBoxes.clear();
      this.snackBar.open(this.i18n.t(I18N.persons.merged), '', { duration: 2000 });
      return { status: 'merged', targetId: target.id, merges };
    } catch {
      this.snackBar.open(this.i18n.t(I18N.persons.merge_error), '', { duration: 3000 });
      return { status: 'failed' };
    }
  }
}
