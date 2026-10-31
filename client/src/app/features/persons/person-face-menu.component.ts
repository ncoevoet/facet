import { Component, inject, input, output, signal, computed, viewChild, ChangeDetectionStrategy } from '@angular/core';
import { MatDialog } from '@angular/material/dialog';
import { MatIconModule } from '@angular/material/icon';
import { MatMenuModule, MatMenuTrigger } from '@angular/material/menu';
import { MatSnackBar } from '@angular/material/snack-bar';
import { Router } from '@angular/router';
import { firstValueFrom } from 'rxjs';
import { ApiService } from '../../core/services/api.service';
import { I18nService } from '../../core/services/i18n.service';
import { UserActivityJournal } from '../../core/agent/user-activity-journal.service';
import { GalleryStore } from '../gallery/gallery.store';
import { PersonFaceBoxesService } from '../../shared/components/photo-card/person-face-boxes.service';
import { PersonHideService } from './person-hide.service';
import { TranslatePipe } from '../../shared/pipes/translate.pipe';
import { isUnnamedPerson } from '../../shared/utils/person-name';
import { i18nKeys, I18N } from '../../core/i18n/keys';

/** The person a menu is about. ``hidden`` decides between Ignore and Restore in person-only mode. */
export interface MenuPerson {
  id: number;
  name: string | null;
  hidden?: boolean;
}

/** What the menu is opened on: a person, a face of a photo, or both. */
export interface PersonFaceMenuTarget {
  person: MenuPerson | null;
  /** A face in the photo at ``path``; without one the menu is person-only. */
  face: { id: number } | null;
}

/**
 * The person/face menu shared by the photo's face layer, the photo page's Persons
 * list and the gallery's person bar: one set of items and handlers.
 *
 * With a face: see the person's photos, change or name the face, use it as the
 * person's picture, find more faces like the person, and "Not X" (that one face
 * only). Person-only: the face items are left out and Ignore (or Restore) is added.
 * Read-only, an unnamed face says that naming needs edition mode, so a click is
 * never silent. After any change the face-box cache is invalidated for the photo
 * and ``changed`` fires, so the host refreshes what it shows.
 */
@Component({
  selector: 'app-person-face-menu',
  imports: [MatIconModule, MatMenuModule, TranslatePipe],
  changeDetection: ChangeDetectionStrategy.Eager,
  host: { class: 'contents' },
  template: `
    <div class="fixed w-0 h-0" [style.left.px]="x()" [style.top.px]="y()"
         [matMenuTriggerFor]="menu" [matMenuTriggerRestoreFocus]="false" (menuClosed)="onClosed()"></div>
    <mat-menu #menu="matMenu">
      @if (view(); as v) {
        <div class="px-4 py-2 text-xs opacity-70 truncate max-w-[16rem]">
          {{ v.name || (I18N.photo_faces.unknown | translate) }}
        </div>
        @if (v.personId) {
          <button mat-menu-item (click)="viewPhotos()">
            <mat-icon>photo_library</mat-icon>
            {{ (v.unnamed ? I18N.photo_faces.view_group_photos : I18N.photo_faces.view_photos) | translate:{ name: v.name || '' } }}
          </button>
        }
        @if (canEdit()) {
          @if (v.hasFace) {
            <button mat-menu-item (click)="changePerson()">
              <mat-icon>manage_accounts</mat-icon>
              {{ (v.personId ? I18N.photo_faces.change_person : I18N.photo_faces.name_face) | translate }}
            </button>
          }
          @if (v.personId) {
            @if (v.hasFace) {
              <button mat-menu-item (click)="usePicture()">
                <mat-icon>account_circle</mat-icon>
                {{ (v.unnamed ? I18N.photo_faces.use_group_picture : I18N.photo_faces.use_picture) | translate:{ name: v.name || '' } }}
              </button>
            }
            <button mat-menu-item (click)="findMore()">
              <mat-icon>person_search</mat-icon>
              {{ (v.unnamed ? I18N.photo_faces.find_more_group : I18N.photo_faces.find_more) | translate:{ name: v.name || '' } }}
            </button>
            @if (v.hasFace) {
              <button mat-menu-item (click)="notThisPerson()">
                <mat-icon>person_remove</mat-icon>
                {{ (v.unnamed ? I18N.photo_faces.not_group : I18N.photo_faces.not_person) | translate:{ name: v.name || '' } }}
              </button>
            } @else {
              <button mat-menu-item (click)="setHidden(!v.hidden)">
                <mat-icon>{{ v.hidden ? 'visibility' : 'block' }}</mat-icon>
                {{ (v.hidden ? I18N.persons.unhide : I18N.persons.hide) | translate }}
              </button>
            }
          }
        } @else if (!v.personId && v.hasFace) {
          <button mat-menu-item disabled>
            <mat-icon>lock</mat-icon>
            {{ I18N.photo_faces.name_needs_edition | translate }}
          </button>
        }
      }
    </mat-menu>
  `,
})
export class PersonFaceMenuComponent {
  protected readonly I18N = i18nKeys();
  private readonly api = inject(ApiService);
  private readonly dialog = inject(MatDialog);
  private readonly snackBar = inject(MatSnackBar);
  private readonly i18n = inject(I18nService);
  private readonly store = inject(GalleryStore);
  private readonly router = inject(Router);
  private readonly journal = inject(UserActivityJournal);
  private readonly faceBoxes = inject(PersonFaceBoxesService);
  private readonly hide = inject(PersonHideService);

  /** The photo the face belongs to; face actions need it. */
  readonly path = input<string | null>(null);
  readonly canEdit = input(false);
  /** After a face or person changed: the host refreshes. */
  readonly changed = output<void>();
  /** After Ignore or Restore, with the person's new state. */
  readonly hiddenChanged = output<{ personId: number; hidden: boolean }>();
  /** When the menu closes, whatever was chosen. */
  readonly closed = output<void>();

  private readonly trigger = viewChild.required(MatMenuTrigger);
  /** What the open menu is about. */
  readonly target = signal<PersonFaceMenuTarget | null>(null);
  protected readonly x = signal(0);
  protected readonly y = signal(0);
  private focusOrigin: HTMLElement | SVGElement | null = null;

  protected readonly view = computed(() => {
    const t = this.target();
    if (!t) return null;
    return {
      personId: t.person?.id ?? null,
      name: t.person?.name ?? null,
      unnamed: isUnnamedPerson(t.person?.name),
      hidden: !!t.person?.hidden,
      hasFace: t.face !== null,
    };
  });

  /**
   * Open the menu at a viewport point. ``focusOrigin`` (a keyboard-opened face, an
   * avatar button) gets the focus back when the menu closes.
   */
  open(target: PersonFaceMenuTarget, x: number, y: number, focusOrigin: HTMLElement | SVGElement | null = null): void {
    this.target.set(target);
    this.x.set(x);
    this.y.set(y);
    this.focusOrigin = focusOrigin;
    this.trigger().openMenu();
  }

  /** Open the menu under ``anchor`` (an avatar button), which gets the focus back on close. */
  openBelow(target: PersonFaceMenuTarget, anchor: HTMLElement): void {
    const rect = anchor.getBoundingClientRect();
    this.open(target, rect.left + rect.width / 2, rect.bottom, anchor);
  }

  protected onClosed(): void {
    this.focusOrigin?.focus();
    this.focusOrigin = null;
    this.closed.emit();
  }

  /** Open the gallery on every photo of the person, named or not. */
  viewPhotos(): void {
    const person = this.target()?.person;
    if (!person) return;
    // Already in the gallery, a navigation to the same route leaves the store's
    // filters (other people among them) in place, so replace them here.
    if (this.router.url.split(/[?#]/)[0] === '/') {
      void this.store.resetFilters()
        .then(() => this.store.updateFilters({ person_id: String(person.id) }))
        .catch(() => this.snackBar.open(this.i18n.t(I18N.errors.action_failed), '', { duration: 3000 }));
      return;
    }
    void this.router.navigate(['/'], { queryParams: { person_id: String(person.id) } });
  }

  /** Make the face the picture on its person's card. */
  async usePicture(): Promise<void> {
    const { person, face } = this.target() ?? {};
    if (!person || !face) return;
    try {
      await firstValueFrom(this.api.post(`/person/${person.id}/avatar`, { face_id: face.id }));
      this.snackBar.open(this.i18n.t(I18N.photo_faces.picture_set), '', { duration: 2000 });
      await this.store.reloadPersonOptions();
      this.changed.emit();
    } catch {
      this.snackBar.open(this.i18n.t(I18N.errors.action_failed), '', { duration: 3000 });
    }
  }

  async changePerson(): Promise<void> {
    const face = this.target()?.face;
    const path = this.path();
    if (!face || !path) return;
    const { PersonSelectorDialogComponent } = await import('../gallery/person-selector-dialog.component');
    const ref = this.dialog.open(PersonSelectorDialogComponent, { width: '95vw', maxWidth: '400px' });
    const result = await firstValueFrom(ref.afterClosed()) as
      | { kind: 'select'; person: { id: number; name: string | null } }
      | { kind: 'create'; name: string }
      | undefined;
    if (!result) return;
    const ok = result.kind === 'create'
      ? (await this.store.createPerson(result.name, [face.id], path)) !== null
      : await this.store.assignFace(face.id, result.person.id, path, result.person.name ?? '');
    this.snackBar.open(
      this.i18n.t(ok ? I18N.notifications.faces_assigned : I18N.errors.action_failed), '', { duration: ok ? 2000 : 3000 });
    if (!ok) return;
    this.faceBoxes.invalidate(path);
    this.changed.emit();
  }

  /** Take this one face off its person; the photo's other faces of that person keep it. */
  async notThisPerson(): Promise<void> {
    const { person, face } = this.target() ?? {};
    const path = this.path();
    if (!person || !face || !path) return;
    try {
      await firstValueFrom(this.api.post(`/face/${face.id}/unassign`));
    } catch {
      this.snackBar.open(this.i18n.t(I18N.photo_faces.unassign_error), '', { duration: 3000 });
      return;
    }
    this.journal.record('person', [path], { action: 'unassign', person_id: person.id });
    this.faceBoxes.invalidate(path);
    this.changed.emit();
  }

  async findMore(): Promise<void> {
    const person = this.target()?.person;
    if (!person) return;
    const { FindMoreFacesDialogComponent } = await import('./find-more-faces-dialog.component');
    const ref = this.dialog.open(FindMoreFacesDialogComponent, {
      data: { personId: person.id, personName: person.name },
      width: '95vw',
      maxWidth: '720px',
    });
    const result = await firstValueFrom(ref.afterClosed()) as { added: number } | undefined;
    if (result && result.added > 0) {
      this.journal.record('person', [], { action: 'find_more', person_id: person.id, count: result.added });
      this.snackBar.open(this.i18n.t(I18N.persons.find_more_added, { count: result.added }), '', { duration: 2000 });
      this.changed.emit();
    }
  }

  /** Ignore (undoable, see ``PersonHideService``) or restore the person, through the persons page's hide/unhide call. */
  async setHidden(hidden: boolean): Promise<void> {
    const person = this.target()?.person;
    if (!person) return;
    if (await this.hide.setHidden(person.id, hidden, () => this.applyHidden(person.id, false))) {
      await this.applyHidden(person.id, hidden);
    }
  }

  private async applyHidden(personId: number, hidden: boolean): Promise<void> {
    await this.store.reloadPersonOptions();
    this.hiddenChanged.emit({ personId, hidden });
    this.changed.emit();
  }
}
